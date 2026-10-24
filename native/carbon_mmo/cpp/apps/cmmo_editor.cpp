// MODULE: app (editor)
// The Carbon MMO Editor's entry point: window + OpenGL context + Dear ImGui backends around editor::Editor.
//
//   cmmo_editor                                   the editor window (macOS / Windows: GLFW)
//   cmmo_editor --selftest --screenshot out.png   drives the real editor (sculpt with the mouse, place, undo,
//                                                 save / open, Play / Stop), saves screenshots, prints
//                                                 EDITOR SELFTEST OK. Linux: headless (EGL); Mac / Windows: hidden window.
//   --levels <dir>  where levels are saved (default ./levels)   --script <py>  the Python init hook
//
// The Python hook (scripts/init_render.py, the Phase 1 pipeline) sets the window title, size and sky colour.
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <set>
#include <string>
#include <vector>

#include "editor/Editor.h"
#include "editor/GL.h"
#include "imgui.h"
#include "ImGuizmo.h"   // after imgui.h
#include "imgui_impl_opengl3.h"
#include "script_host/ScriptHost.h"

#if defined( CMMO_WITH_GLFW )
#include "imgui_impl_glfw.h"
#define GLFW_INCLUDE_NONE
#include <GLFW/glfw3.h>
#elif defined( CMMO_WITH_EGL )
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <dlfcn.h>
#endif

using namespace cmmo;
using cmmo::world::ActorType;

namespace
{
// ------------------------------------------------------------------------------------------ PNG (stored deflate)
uint32_t Crc( const uint8_t* d, size_t n, uint32_t c = 0xFFFFFFFFu )
{
	for( size_t i = 0; i < n; ++i )
	{
		c ^= d[i];
		for( int k = 0; k < 8; ++k ) c = ( c >> 1 ) ^ ( 0xEDB88320u & ( 0u - ( c & 1u ) ) );
	}
	return c;
}
bool WritePng( const std::string& path, int w, int h, const std::vector<uint8_t>& rgba )
{
	std::vector<uint8_t> raw;
	raw.reserve( size_t( h ) * ( size_t( w ) * 4 + 1 ) );
	for( int y = 0; y < h; ++y )
	{
		raw.push_back( 0 );
		raw.insert( raw.end(), rgba.begin() + y * w * 4, rgba.begin() + ( y + 1 ) * w * 4 );
	}
	std::vector<uint8_t> z = { 0x78, 0x01 };
	uint32_t a = 1, b = 0;
	for( uint8_t v : raw ) { a = ( a + v ) % 65521; b = ( b + a ) % 65521; }
	for( size_t off = 0; off < raw.size() || off == 0; )
	{
		const size_t n = std::min<size_t>( 65535, raw.size() - off );
		const bool last = off + n >= raw.size();
		z.push_back( last ? 1 : 0 );
		z.push_back( uint8_t( n ) ); z.push_back( uint8_t( n >> 8 ) ); z.push_back( uint8_t( ~n ) ); z.push_back( uint8_t( ~n >> 8 ) );
		z.insert( z.end(), raw.begin() + off, raw.begin() + off + n );
		off += n;
		if( last ) break;
	}
	const uint32_t adler = ( b << 16 ) | a;
	for( int s = 24; s >= 0; s -= 8 ) z.push_back( uint8_t( adler >> s ) );
	std::ofstream f( path, std::ios::binary );
	if( !f ) return false;
	auto be = [&]( uint32_t v ) { uint8_t q[4] = { uint8_t( v >> 24 ), uint8_t( v >> 16 ), uint8_t( v >> 8 ), uint8_t( v ) }; f.write( (const char*)q, 4 ); };
	auto chunk = [&]( const char* type, const std::vector<uint8_t>& data ) {
		be( uint32_t( data.size() ) );
		std::vector<uint8_t> td( type, type + 4 );
		td.insert( td.end(), data.begin(), data.end() );
		f.write( (const char*)td.data(), std::streamsize( td.size() ) );
		be( Crc( td.data(), td.size() ) ^ 0xFFFFFFFFu );
	};
	const uint8_t sig[8] = { 137, 80, 78, 71, 13, 10, 26, 10 };
	f.write( (const char*)sig, 8 );
	std::vector<uint8_t> ihdr = { uint8_t( w >> 24 ), uint8_t( w >> 16 ), uint8_t( w >> 8 ), uint8_t( w ), uint8_t( h >> 24 ), uint8_t( h >> 16 ), uint8_t( h >> 8 ), uint8_t( h ), 8, 6, 0, 0, 0 };
	chunk( "IHDR", ihdr );
	chunk( "IDAT", z );
	chunk( "IEND", {} );
	return bool( f );
}

int DistinctColors( const std::vector<uint8_t>& px )
{
	std::set<uint32_t> seen;
	for( size_t i = 0; i + 3 < px.size() && seen.size() < 5000; i += 4 * 7 ) seen.insert( ( px[i] >> 3 ) << 10 | ( px[i + 1] >> 3 ) << 5 | ( px[i + 2] >> 3 ) );
	return int( seen.size() );
}

// ------------------------------------------------------------------------------------------ self-test
struct SelfTest
{
	editor::Editor& ed;
	std::string shotPath, levelsDir;
	int frame = 0, pass = 0, fail = 0, step = 0, wait = 0;
	float h0 = 0;
	size_t count0 = 0;
	uint32_t cube = 0;
	Vector3 startPos;
	std::vector<uint8_t> playShot;
	int playW = 0, playH = 0;

	void Check( const char* name, bool ok, const std::string& detail = "" )
	{
		( ok ? pass : fail )++;
		std::printf( "  [%s] %s%s%s\n", ok ? "PASS" : "FAIL", name, ok || detail.empty() ? "" : " <- ", ok ? "" : detail.c_str() );
		std::fflush( stdout );
	}
	// returns true when finished. Called before ImGui::NewFrame() each frame (so injected input lands in that frame).
	bool Before()
	{
		ImGuiIO& io = ImGui::GetIO();
		io.DeltaTime = 1.0f / 60.0f;
		if( wait > 0 ) { --wait; return false; }
		const float cx = ed.ViewOriginX() + ed.ViewW() * 0.5f, cy = ed.ViewOriginY() + ed.ViewH() * 0.5f;
		switch( step )
		{
		case 0:   // let the layout settle
			wait = 3;
			++step;
			break;
		case 1:
		{
			Check( "a new level has ground, a sun, a Player Start and a Creature Spawn", ed.Scene().Entities().size() == 4 );
			// the gizmo and the engine compose transforms the same way
			world::Transform t;
			t.position = Vector3( 1, 2, 3 );
			t.rotation = Vector3( 20, 35, -15 );
			t.scale = Vector3( 1.5f, 0.5f, 2 );
			float m[16];
			ImGuizmo::RecomposeMatrixFromComponents( &t.position.x, &t.rotation.x, &t.scale.x, m );
			const Matrix w = t.World();
			float err = 0;
			for( int i = 0; i < 16; ++i ) err = std::max( err, std::fabs( m[i] - ( &w._11 )[i] ) );
			Check( "ImGuizmo's handles and the engine's Carbon transforms agree", err < 1e-4f, std::to_string( err ) );
			h0 = ed.Scene().GroundAt( 0, 0 );
			ed.BrushOn() = true;
			ed.Brush().mode = world::Brush::Raise;
			ed.Brush().strength = 0.6f;
			io.AddMousePosEvent( cx, cy );
			++step;
			wait = 2;
			break;
		}
		case 2:   // a real mouse drag in the viewport sculpts
			io.AddMouseButtonEvent( 0, true );
			++step;
			wait = 12;
			break;
		case 3:
			io.AddMouseButtonEvent( 0, false );
			++step;
			wait = 2;
			break;
		case 4:
		{
			const float h1 = ed.Scene().GroundAt( 0, 0 );
			Check( "Terrain brush: a mouse drag in the viewport raises the ground", h1 > h0 + 1.0f, std::to_string( h0 ) + " -> " + std::to_string( h1 ) );
			ed.BrushOn() = false;
			ed.Undo();
			Check( "Undo takes the whole stroke back", std::fabs( ed.Scene().GroundAt( 0, 0 ) - h0 ) < 1e-4f );
			ed.Redo();
			Check( "Redo brings it back", ed.Scene().GroundAt( 0, 0 ) > h0 + 1.0f );
			count0 = ed.Scene().Entities().size();
			cube = ed.Place( ActorType::Mesh, Vector3( 6, ed.Scene().GroundAt( 6, 4 ), 4 ) );
			Check( "Place Actors adds a shape and selects it", ed.Scene().Entities().size() == count0 + 1 && ed.Selected() == cube );
			ed.Undo();
			Check( "Undo removes it", ed.Scene().Entities().size() == count0 && !ed.Scene().Find( cube ) );
			ed.Redo();
			ed.Select( cube );
			Check( "Redo puts it back", ed.Scene().Find( cube ) != nullptr );
			ed.DuplicateSelected();
			Check( "Duplicate (Ctrl+D) copies it", ed.Scene().Entities().size() == count0 + 2 );
			io.AddMousePosEvent( cx + 40, cy + 30 );   // hover away from the gizmo, then click the terrain: select by picking
			++step;
			wait = 2;
			break;
		}
		case 5:
			ed.Select( 0 );
			io.AddMouseButtonEvent( 0, true );
			++step;
			wait = 1;
			break;
		case 6:
			io.AddMouseButtonEvent( 0, false );
			++step;
			wait = 1;
			break;
		case 7:
		{
			const world::Entity* picked = ed.Scene().Find( ed.Selected() );
			Check( "clicking in the viewport selects what is under the mouse", picked && picked->type == ActorType::Terrain, picked ? picked->name : "nothing" );
			const std::string path = levelsDir + "/selftest.level.json";
			const size_t n = ed.Scene().Entities().size();
			const float h = ed.Scene().GroundAt( 0, 0 );
			Check( "Save Level", ed.SaveLevel( path ) );
			ed.NewLevel();
			Check( "Open Level brings every actor and the sculpted ground back", ed.OpenLevel( path ) && ed.Scene().Entities().size() == n &&
																				  std::fabs( ed.Scene().GroundAt( 0, 0 ) - h ) < 1e-3f );
			count0 = n;
			Check( "Play starts", ed.Play( true ) && ed.Session() && ed.Session()->Creatures().size() == 3 );
			startPos = ed.Session()->PlayerPosition();
			ed.InjectedInput().forward = true;
			++step;
			wait = 60;
			break;
		}
		case 8:
		{
			ed.InjectedInput().forward = false;
			const Vector3 p = ed.Session()->PlayerPosition();
			Check( "W walks the player forward and keeps the feet on the ground", startPos.z - p.z > 4.0f &&
																				  std::fabs( p.y - ed.Session()->World().GroundAt( p.x, p.z ) ) < 0.05f,
				   std::to_string( startPos.z ) + " -> " + std::to_string( p.z ) );
			ed.InjectedInput().turning = true;
			ed.InjectedInput().mouseDX = 120;
			++step;
			wait = 2;
			break;
		}
		case 9:
			ed.InjectedInput().turning = false;
			Check( "right-drag turns the character", std::fabs( ed.Session()->PlayerYaw() ) > 0.3f );
			playShot = ed.Render().ReadPixels();
			playW = ed.Render().Width();
			playH = ed.Render().Height();
			Check( "the Play view renders the world (not a blank frame)", DistinctColors( playShot ) > 40, std::to_string( DistinctColors( playShot ) ) );
			io.AddKeyEvent( ImGuiKey_Escape, true );
			++step;
			wait = 1;
			break;
		case 10:
			io.AddKeyEvent( ImGuiKey_Escape, false );
			Check( "Esc stops and the level is exactly as it was", !ed.Playing() && ed.Scene().Entities().size() == count0 );
			++step;
			wait = 3;
			break;
		default:
			return true;
		}
		return false;
	}
};

void ApplyStyle()
{
	ImGuiStyle& s = ImGui::GetStyle();
	ImGui::StyleColorsDark();
	s.WindowRounding = 3;
	s.FrameRounding = 3;
	s.TabRounding = 3;
	s.WindowPadding = ImVec2( 8, 8 );
	s.ItemSpacing = ImVec2( 6, 5 );
	ImVec4* c = s.Colors;
	c[ImGuiCol_WindowBg] = ImVec4( 0.12f, 0.12f, 0.13f, 1 );
	c[ImGuiCol_TitleBgActive] = ImVec4( 0.16f, 0.17f, 0.19f, 1 );
	c[ImGuiCol_Tab] = ImVec4( 0.15f, 0.16f, 0.17f, 1 );
	c[ImGuiCol_TabSelected] = ImVec4( 0.22f, 0.36f, 0.56f, 1 );
	c[ImGuiCol_Button] = ImVec4( 0.22f, 0.24f, 0.27f, 1 );
	c[ImGuiCol_ButtonHovered] = ImVec4( 0.28f, 0.42f, 0.62f, 1 );
	c[ImGuiCol_Header] = ImVec4( 0.22f, 0.36f, 0.56f, 0.7f );
}
}

int main( int argc, char** argv )
{
	bool selftest = false;
	std::string shot, levels = "levels", script = std::string( CMMO_SOURCE_DIR ) + "/scripts/init_render.py";
	for( int i = 1; i < argc; ++i )
	{
		const std::string a = argv[i];
		if( a == "--selftest" ) selftest = true;
		else if( a == "--screenshot" && i + 1 < argc ) shot = argv[++i];
		else if( a == "--levels" && i + 1 < argc ) levels = argv[++i];
		else if( a == "--script" && i + 1 < argc ) script = argv[++i];
		else
		{
			std::printf( "usage: %s [--selftest] [--screenshot out.png] [--levels dir] [--script init.py]\n", argv[0] );
			return 2;
		}
	}

	// ---- the Python init hook (same pipeline as Phase 1): title, size, sky colour
	editor::EditorSettings settings;
	settings.levelsDir = levels;
	int width = 1600, height = 900;
	{
		cmmo::RenderConfig cfg;
		cfg.title = settings.title;
		cfg.width = width;
		cfg.height = height;
		cmmo::ScriptHost host( argv[0] );
		std::string err;
		if( host.RunInitHook( script, cfg, err ) )
		{
			settings.title = cfg.title;
			width = std::max( 1600, cfg.width );   // an editor needs room: at least 1600 x 900
			height = std::max( 900, cfg.height );
			settings.clear = Vector3( cfg.clear_color.r * 0.6f + 0.25f, cfg.clear_color.g * 0.6f + 0.35f, cfg.clear_color.b * 0.5f + 0.5f );
		}
		else
			std::printf( "[editor] init hook skipped: %s\n", err.c_str() );
	}

	// ---- window / context
#if defined( CMMO_WITH_GLFW )
	if( !glfwInit() ) { std::fprintf( stderr, "GLFW failed to start\n" ); return 1; }
	glfwWindowHint( GLFW_CONTEXT_VERSION_MAJOR, 3 );
	glfwWindowHint( GLFW_CONTEXT_VERSION_MINOR, 3 );
	glfwWindowHint( GLFW_OPENGL_PROFILE, GLFW_OPENGL_CORE_PROFILE );
	glfwWindowHint( GLFW_OPENGL_FORWARD_COMPAT, GLFW_TRUE );   // required on macOS
	if( selftest ) glfwWindowHint( GLFW_VISIBLE, GLFW_FALSE );
	GLFWwindow* window = glfwCreateWindow( width, height, settings.title.c_str(), nullptr, nullptr );
	if( !window ) { std::fprintf( stderr, "could not open an OpenGL 3.3 window\n" ); glfwTerminate(); return 1; }
	glfwMakeContextCurrent( window );
	glfwSwapInterval( 1 );
	if( const char* missing = gl::Load( []( const char* n ) { return (void*)glfwGetProcAddress( n ); } ) )
	{
		std::fprintf( stderr, "OpenGL function missing: %s\n", missing );
		return 1;
	}
#elif defined( CMMO_WITH_EGL )
	void* lib = dlopen( "libEGL.so.1", RTLD_NOW | RTLD_LOCAL );
	if( !lib ) { std::fprintf( stderr, "headless: no libEGL.so.1\n" ); return 1; }
#define EGLF( name ) auto name = reinterpret_cast<decltype( &::name )>( dlsym( lib, #name ) )
	EGLF( eglGetProcAddress ); EGLF( eglInitialize ); EGLF( eglChooseConfig ); EGLF( eglBindAPI ); EGLF( eglCreateContext );
	EGLF( eglMakeCurrent ); EGLF( eglTerminate ); EGLF( eglGetError );
	auto getPlatformDisplay = reinterpret_cast<PFNEGLGETPLATFORMDISPLAYEXTPROC>( eglGetProcAddress( "eglGetPlatformDisplayEXT" ) );
	EGLDisplay dpy = getPlatformDisplay ? getPlatformDisplay( EGL_PLATFORM_SURFACELESS_MESA, EGL_DEFAULT_DISPLAY, nullptr ) : EGL_NO_DISPLAY;
	EGLint maj = 0, min = 0;
	if( dpy == EGL_NO_DISPLAY || !eglInitialize( dpy, &maj, &min ) ) { std::fprintf( stderr, "headless: EGL display failed\n" ); return 1; }
	const EGLint cfgAttr[] = { EGL_SURFACE_TYPE, 0, EGL_RENDERABLE_TYPE, EGL_OPENGL_BIT, EGL_NONE };
	EGLConfig eglCfg;
	EGLint n = 0;
	eglChooseConfig( dpy, cfgAttr, &eglCfg, 1, &n );
	eglBindAPI( EGL_OPENGL_API );
	const EGLint ctxAttr[] = { EGL_CONTEXT_MAJOR_VERSION, 3, EGL_CONTEXT_MINOR_VERSION, 3, EGL_CONTEXT_OPENGL_PROFILE_MASK, EGL_CONTEXT_OPENGL_CORE_PROFILE_BIT, EGL_NONE };
	EGLContext ctx = eglCreateContext( dpy, n ? eglCfg : nullptr, EGL_NO_CONTEXT, ctxAttr );
	if( ctx == EGL_NO_CONTEXT || !eglMakeCurrent( dpy, EGL_NO_SURFACE, EGL_NO_SURFACE, ctx ) )
	{
		std::fprintf( stderr, "headless: no OpenGL 3.3 core context (EGL error 0x%x)\n", eglGetError() );
		return 1;
	}
	static decltype( eglGetProcAddress ) s_proc = eglGetProcAddress;
	if( const char* missing = gl::Load( []( const char* nm ) { return (void*)s_proc( nm ); } ) )
	{
		std::fprintf( stderr, "OpenGL function missing: %s\n", missing );
		return 1;
	}
	if( !selftest ) std::printf( "[editor] no window system in this build: running the self-test\n" );
	selftest = true;
	// an offscreen "window" the UI is drawn into
	GLuint screenFbo = 0, screenTex = 0;
	gl::glGenFramebuffers( 1, &screenFbo );
	gl::glGenTextures( 1, &screenTex );
	gl::glBindTexture( GL_TEXTURE_2D, screenTex );
	gl::glTexImage2D( GL_TEXTURE_2D, 0, GL_RGBA8, width, height, 0, GL_RGBA, GL_UNSIGNED_BYTE, nullptr );
	gl::glBindFramebuffer( GL_FRAMEBUFFER, screenFbo );
	gl::glFramebufferTexture2D( GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, screenTex, 0 );
#else
#error "cmmo_editor needs CMMO_WITH_GLFW (macOS / Windows) or CMMO_WITH_EGL (Linux headless)"
#endif
	std::printf( "[editor] OpenGL %s\n", (const char*)gl::glGetString( GL_VERSION ) );

	// ---- ImGui
	IMGUI_CHECKVERSION();
	ImGui::CreateContext();
	ImGuiIO& io = ImGui::GetIO();
	io.ConfigFlags |= ImGuiConfigFlags_DockingEnable | ImGuiConfigFlags_NavEnableKeyboard;
	io.IniFilename = selftest ? nullptr : "cmmo_editor_layout.ini";
	ApplyStyle();
#if defined( CMMO_WITH_GLFW )
	ImGui_ImplGlfw_InitForOpenGL( window, true );
#else
	io.DisplaySize = ImVec2( float( width ), float( height ) );
	io.BackendPlatformName = "cmmo_headless";
#endif
	ImGui_ImplOpenGL3_Init( "#version 330 core" );

	editor::Editor ed;
	std::string err;
	if( !ed.Init( settings, err ) )
	{
		std::fprintf( stderr, "editor failed to start: %s\n", err.c_str() );
		return 1;
	}

	SelfTest test{ ed, shot, levels };
	if( selftest ) std::printf( "[editor] self-test\n" );
	auto last = std::chrono::steady_clock::now();
	bool done = false;
	int frames = 0;
	while( !done )
	{
#if defined( CMMO_WITH_GLFW )
		glfwPollEvents();
		if( glfwWindowShouldClose( window ) ) break;
#endif
		const auto now = std::chrono::steady_clock::now();
		io.DeltaTime = std::max( 1e-4f, std::chrono::duration<float>( now - last ).count() );
		last = now;
		if( selftest && test.Before() ) done = true;
		ImGui_ImplOpenGL3_NewFrame();
#if defined( CMMO_WITH_GLFW )
		ImGui_ImplGlfw_NewFrame();
		if( selftest ) io.DeltaTime = 1.0f / 60.0f;
#endif
		ImGui::NewFrame();
		ed.Frame( io.DeltaTime );
		ImGui::Render();
#if defined( CMMO_WITH_GLFW )
		int fw = 0, fh = 0;
		glfwGetFramebufferSize( window, &fw, &fh );
		gl::glBindFramebuffer( GL_FRAMEBUFFER, 0 );
#else
		const int fw = width, fh = height;
		gl::glBindFramebuffer( GL_FRAMEBUFFER, screenFbo );
#endif
		gl::glViewport( 0, 0, fw, fh );
		gl::glClearColor( 0.08f, 0.08f, 0.09f, 1 );
		gl::glClear( GL_COLOR_BUFFER_BIT );
		ImGui_ImplOpenGL3_RenderDrawData( ImGui::GetDrawData() );
		if( done && !shot.empty() )
		{
			std::vector<uint8_t> px( size_t( fw * fh * 4 ) ), flip( px.size() );
			gl::glPixelStorei( GL_PACK_ALIGNMENT, 1 );
			gl::glReadPixels( 0, 0, fw, fh, GL_RGBA, GL_UNSIGNED_BYTE, px.data() );
			for( int y = 0; y < fh; ++y ) std::memcpy( &flip[size_t( y * fw * 4 )], &px[size_t( ( fh - 1 - y ) * fw * 4 )], size_t( fw * 4 ) );
			const bool okShot = WritePng( shot, fw, fh, flip );
			test.Check( "the editor window renders (screenshot saved)", okShot && DistinctColors( flip ) > 60, shot );
			std::string playPath = shot.substr( 0, shot.size() - 4 ) + "_play.png";
			if( !test.playShot.empty() ) WritePng( playPath, test.playW, test.playH, test.playShot );
		}
#if defined( CMMO_WITH_GLFW )
		glfwSwapBuffers( window );
#endif
		if( ed.WantsQuit() ) break;
		if( selftest && ++frames > 600 ) { test.Check( "self-test finished in time", false ); break; }
	}

	ed.Shutdown();
	ImGui_ImplOpenGL3_Shutdown();
#if defined( CMMO_WITH_GLFW )
	ImGui_ImplGlfw_Shutdown();
	ImGui::DestroyContext();
	glfwDestroyWindow( window );
	glfwTerminate();
#else
	ImGui::DestroyContext();
#endif
	if( selftest )
	{
		std::printf( "\n%d passed, %d failed\n%s\n", test.pass, test.fail, test.fail ? "EDITOR SELFTEST FAILED" : "EDITOR SELFTEST OK" );
		return test.fail ? 1 : 0;
	}
	return 0;
}
