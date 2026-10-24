// MODULE: editor
#include "editor/Editor.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <filesystem>

#include "imgui.h"
#include "ImGuizmo.h"   // after imgui.h
#include "imgui_internal.h"   // DockBuilder: the default layout

using cmmo::world::ActorType;
namespace fs = std::filesystem;

namespace cmmo::editor
{
namespace
{
constexpr float kPi = 3.14159265358979f;

struct PaintColor
{
	const char* name;
	Vector3 rgb;
};
const PaintColor kPaints[] = {
	{ "Grass", Vector3( 0.31f, 0.48f, 0.2f ) }, { "Dirt", Vector3( 0.48f, 0.35f, 0.23f ) }, { "Rock", Vector3( 0.49f, 0.49f, 0.48f ) },
	{ "Snow", Vector3( 0.93f, 0.95f, 0.96f ) }, { "Sand", Vector3( 0.79f, 0.7f, 0.49f ) },
};

const char* kShapes[] = { "cube", "sphere", "cylinder", "cone", "plane" };

ImVec4 Col( const Vector3& c, float a = 1 ) { return ImVec4( c.x, c.y, c.z, a ); }
}

// ------------------------------------------------------------------------------------------------ lifecycle
bool Editor::Init( const EditorSettings& settings, std::string& error )
{
	m_settings = settings;
	if( !m_renderer.Init( error ) ) return false;
	NewLevel();
	Print( "Carbon MMO Editor ready. Alt+P plays, Esc stops." );
	return true;
}

void Editor::Shutdown()
{
	m_play.reset();
	m_renderer.Shutdown();
}

void Editor::Print( const std::string& line )
{
	m_log.push_back( line );
	if( m_log.size() > 500 ) m_log.erase( m_log.begin(), m_log.begin() + 100 );
	std::printf( "[editor] %s\n", line.c_str() );
	std::fflush( stdout );
}

// ------------------------------------------------------------------------------------------------ actions
void Editor::NewLevel()
{
	Stop();
	m_scene.Clear();
	// a playable starting point: ground, a sun, where you start, something to fight
	const uint32_t terrain = m_scene.Create( ActorType::Terrain ).id;
	world::Entity& sun = m_scene.Create( ActorType::DirLight );
	sun.transform.position = Vector3( 0, 30, 0 );
	sun.transform.rotation = Vector3( -50, 35, 0 );
	m_scene.Create( ActorType::PlayerStart ).transform.position = Vector3( 0, 0, 20 );
	m_scene.Create( ActorType::CreatureSpawn ).transform.position = Vector3( 14, 0, -6 );
	m_selected = terrain;
	m_undo.clear();
	m_redo.clear();
	m_current = m_scene.ToJson().dump();
	levelPath.clear();
	m_pivot = Vector3( 0, 0, 0 );
	m_dist = 60;
	OrbitFromAngles();
}

bool Editor::SaveLevel( const std::string& path )
{
	std::string err;
	std::error_code ec;
	fs::create_directories( fs::path( path ).parent_path().empty() ? fs::path( "." ) : fs::path( path ).parent_path(), ec );
	if( !world::SaveLevel( m_scene, path, &err ) )
	{
		Print( "Save failed: " + err );
		return false;
	}
	levelPath = path;
	Print( "Saved " + path );
	return true;
}

bool Editor::OpenLevel( const std::string& path )
{
	Stop();
	world::Scene loaded;
	std::string err;
	if( !world::LoadLevel( loaded, path, &err ) )
	{
		Print( "Open failed: " + err );
		return false;
	}
	m_scene = std::move( loaded );
	m_selected = 0;
	m_undo.clear();
	m_redo.clear();
	m_current = m_scene.ToJson().dump();
	levelPath = path;
	Print( "Opened " + path + " (" + std::to_string( m_scene.Entities().size() ) + " actors)" );
	return true;
}

uint32_t Editor::Place( ActorType type, const Vector3& at )
{
	if( Playing() ) return 0;
	world::Entity& e = m_scene.Create( type );
	e.transform.position = at;
	if( type == ActorType::PointLight ) e.transform.position.y += 3;
	if( type == ActorType::DirLight ) { e.transform.position.y += 20; e.transform.rotation = Vector3( -50, 35, 0 ); }
	if( type == ActorType::TriggerBox ) e.transform.position.y += 1;
	const uint32_t id = e.id;
	m_selected = id;
	Commit( "Place" );
	Print( std::string( "Placed " ) + world::InfoOf( type ).label + " (" + m_scene.Find( id )->name + ")" );
	return id;
}

bool Editor::DeleteSelected()
{
	if( Playing() || !m_scene.Find( m_selected ) ) return false;
	const std::string name = m_scene.Find( m_selected )->name;
	m_scene.Remove( m_selected );
	m_selected = 0;
	Commit( "Delete" );
	Print( "Deleted " + name );
	return true;
}

uint32_t Editor::DuplicateSelected()
{
	const world::Entity* src = m_scene.Find( m_selected );
	if( Playing() || !src ) return 0;
	world::Entity copy = *src;
	if( copy.terrain ) copy.terrain = std::make_shared<world::Terrain>( *copy.terrain );
	copy.id = m_scene.nextId++;
	std::string stem = copy.name;
	while( !stem.empty() && std::isdigit( (unsigned char)stem.back() ) ) stem.pop_back();
	copy.name = m_scene.UniqueName( stem.empty() ? "Actor" : stem );
	copy.transform.position += Vector3( 2, 0, 0 );
	m_scene.Entities().push_back( copy );
	m_selected = copy.id;
	Commit( "Duplicate" );
	return copy.id;
}

void Editor::Commit( const char* what )
{
	std::string now = m_scene.ToJson().dump();
	if( now == m_current ) return;
	m_undo.push_back( std::move( m_current ) );
	if( m_undo.size() > 60 ) m_undo.pop_front();
	m_redo.clear();
	m_current = std::move( now );
	(void)what;
}

bool Editor::Undo()
{
	if( Playing() || m_undo.empty() ) return false;
	m_redo.push_back( m_current );
	m_current = m_undo.back();
	m_undo.pop_back();
	m_scene.FromJson( world::json::parse( m_current ) );
	if( !m_scene.Find( m_selected ) ) m_selected = 0;
	return true;
}

bool Editor::Redo()
{
	if( Playing() || m_redo.empty() ) return false;
	m_undo.push_back( m_current );
	m_current = m_redo.back();
	m_redo.pop_back();
	m_scene.FromJson( world::json::parse( m_current ) );
	if( !m_scene.Find( m_selected ) ) m_selected = 0;
	return true;
}

bool Editor::Play( bool possess )
{
	if( Playing() ) return false;
	m_play = std::make_unique<world::PlaySession>( m_scene, possess );
	m_brushDragging = false;
	Print( possess ? "Playing - W/S move, A/D turn, Q/E strafe, Space jumps, right-drag turns, left-drag looks, wheel zooms, Esc stops."
				   : "Simulating - creatures run, the editor camera stays. Esc stops." );
	return true;
}

void Editor::Stop()
{
	if( !m_play ) return;
	Print( "Stopped after " + std::to_string( int( m_play->Time() * 10 ) / 10.0f ).substr( 0, 4 ) + " s - the level is as it was." );
	m_play.reset();
}

bool Editor::Sculpt( const Vector3& p )
{
	for( auto& e : m_scene.Entities() )
	{
		if( e.type != ActorType::Terrain || !e.terrain ) continue;
		const float lx = p.x - e.transform.position.x, lz = p.z - e.transform.position.z;
		if( !e.terrain->Inside( lx, lz ) ) continue;
		world::Brush b = m_brush;
		b.flattenHeight -= e.transform.position.y;
		return e.terrain->Sculpt( lx, lz, b ) > 0;
	}
	return false;
}

void Editor::OrbitFromAngles()
{
	const float cp = std::cos( m_pitch );
	m_cam.target = m_pivot;
	m_cam.eye = m_pivot + Vector3( std::sin( m_yaw ) * cp, -std::sin( m_pitch ), std::cos( m_yaw ) * cp ) * m_dist;
}

void Editor::FrameSelected()
{
	const world::Entity* e = m_scene.Find( m_selected );
	if( !e ) return;
	m_pivot = e->transform.position;
	if( e->type == ActorType::Terrain && e->terrain ) m_dist = e->terrain->Size() * 0.7f;
	else m_dist = std::max( 6.0f, 4.0f * std::max( e->transform.scale.x, std::max( e->transform.scale.y, e->transform.scale.z ) ) );
	OrbitFromAngles();
}

Vector3 Editor::PlacementPoint()
{
	// where the middle of the viewport looks at the ground
	Vector3 o, d, hit;
	m_cam.Ray( m_viewW * 0.5f, m_viewH * 0.5f, m_viewW, m_viewH, o, d );
	if( m_scene.RaycastTerrain( o, d, hit ) ) return hit;
	if( d.y < -1e-3f ) return o + d * ( -o.y / d.y );
	return Vector3( m_pivot.x, 0, m_pivot.z );
}

// ------------------------------------------------------------------------------------------------ frame
void Editor::Frame( float dt )
{
	ImGuizmo::BeginFrame();
	const ImGuiID dock = ImGui::DockSpaceOverViewport( 0, nullptr, ImGuiDockNodeFlags_None );
	static bool laidOut = false;
	if( !laidOut )
	{
		laidOut = true;
		ImGuiDockNode* node = ImGui::DockBuilderGetNode( dock );
		if( !node || node->IsLeafNode() )   // first run (no saved layout): Unreal-like default arrangement
		{
			ImGui::DockBuilderRemoveNode( dock );
			ImGui::DockBuilderAddNode( dock, ImGuiDockNodeFlags_DockSpace );
			ImGui::DockBuilderSetNodeSize( dock, ImGui::GetMainViewport()->WorkSize );
			ImGuiID center = dock;
			const ImGuiID left = ImGui::DockBuilderSplitNode( center, ImGuiDir_Left, 0.18f, nullptr, &center );
			const ImGuiID right = ImGui::DockBuilderSplitNode( center, ImGuiDir_Right, 0.26f, nullptr, &center );
			const ImGuiID bottom = ImGui::DockBuilderSplitNode( center, ImGuiDir_Down, 0.24f, nullptr, &center );
			ImGuiID leftBottom = 0;
			const ImGuiID leftTop = ImGui::DockBuilderSplitNode( left, ImGuiDir_Up, 0.5f, nullptr, &leftBottom );
			ImGuiID rightBottom = 0;
			const ImGuiID rightTop = ImGui::DockBuilderSplitNode( right, ImGuiDir_Up, 0.55f, nullptr, &rightBottom );
			ImGui::DockBuilderDockWindow( "Viewport", center );
			ImGui::DockBuilderDockWindow( "Place Actors", leftTop );
			ImGui::DockBuilderDockWindow( "Outliner", leftBottom );
			ImGui::DockBuilderDockWindow( "Details", rightTop );
			ImGui::DockBuilderDockWindow( "Terrain", rightBottom );
			ImGui::DockBuilderDockWindow( "Output", bottom );
			ImGui::DockBuilderDockWindow( "Levels", bottom );
			ImGui::DockBuilderFinish( dock );
		}
	}
	MenuBar();
	Hotkeys();
	ViewportPanel( dt );
	PlacePanel();
	OutlinerPanel();
	DetailsPanel();
	TerrainPanel();
	LevelsPanel();
	OutputPanel();
	if( m_showDemo ) ImGui::ShowDemoWindow( &m_showDemo );
	if( m_play )
		for( auto& line : m_play->TakeLog() ) Print( line );
}

void Editor::MenuBar()
{
	if( !ImGui::BeginMainMenuBar() ) return;
	if( ImGui::BeginMenu( "File" ) )
	{
		if( ImGui::MenuItem( "New Level" ) ) NewLevel();
		if( ImGui::MenuItem( "Save Level", "Ctrl+S" ) ) SaveLevel( levelPath.empty() ? m_settings.levelsDir + "/" + m_saveName + ".level.json" : levelPath );
		ImGui::Separator();
		if( ImGui::MenuItem( "Quit" ) ) m_quit = true;
		ImGui::EndMenu();
	}
	if( ImGui::BeginMenu( "Edit" ) )
	{
		if( ImGui::MenuItem( "Undo", "Ctrl+Z", false, !m_undo.empty() && !Playing() ) ) Undo();
		if( ImGui::MenuItem( "Redo", "Ctrl+Shift+Z", false, !m_redo.empty() && !Playing() ) ) Redo();
		ImGui::Separator();
		if( ImGui::MenuItem( "Duplicate", "Ctrl+D", false, m_selected != 0 ) ) DuplicateSelected();
		if( ImGui::MenuItem( "Delete", "Del", false, m_selected != 0 ) ) DeleteSelected();
		if( ImGui::MenuItem( "Frame Selected", "F", false, m_selected != 0 ) ) FrameSelected();
		ImGui::EndMenu();
	}
	if( ImGui::BeginMenu( "Play" ) )
	{
		if( ImGui::MenuItem( "Play in Editor", "Alt+P", false, !Playing() ) ) Play( true );
		if( ImGui::MenuItem( "Simulate", nullptr, false, !Playing() ) ) Play( false );
		if( ImGui::MenuItem( "Stop", "Esc", false, Playing() ) ) Stop();
		ImGui::EndMenu();
	}
	if( ImGui::BeginMenu( "Help" ) )
	{
		ImGui::MenuItem( "ImGui demo (widgets)", nullptr, &m_showDemo );
		ImGui::TextDisabled( "Viewport: Alt+LMB orbit, Alt+MMB pan, Alt+RMB / wheel zoom, F frame" );
		ImGui::TextDisabled( "Q select, W move, E rotate, R scale, Alt+P play, Esc stop" );
		ImGui::EndMenu();
	}
	ImGui::SameLine( ImGui::GetWindowWidth() * 0.5f - 60 );
	if( !Playing() )
	{
		if( ImGui::Button( "  Play  " ) ) Play( true );
		ImGui::SameLine();
		if( ImGui::Button( "Simulate" ) ) Play( false );
	}
	else
	{
		ImGui::PushStyleColor( ImGuiCol_Button, ImVec4( 0.75f, 0.2f, 0.18f, 1 ) );
		if( ImGui::Button( "  Stop  " ) ) Stop();
		ImGui::PopStyleColor();
		ImGui::SameLine();
		ImGui::TextColored( ImVec4( 0.35f, 0.9f, 0.5f, 1 ), "PLAYING %.1f s", m_play->Time() );
	}
	ImGui::EndMainMenuBar();
}

void Editor::Hotkeys()
{
	ImGuiIO& io = ImGui::GetIO();
	if( Playing() )
	{
		if( ImGui::IsKeyPressed( ImGuiKey_Escape, false ) ) Stop();
		return;
	}
	if( ImGui::IsKeyPressed( ImGuiKey_P, false ) && io.KeyAlt ) { Play( true ); return; }
	if( ImGui::Shortcut( ImGuiMod_Ctrl | ImGuiKey_Z, ImGuiInputFlags_RouteGlobal ) ) Undo();
	if( ImGui::Shortcut( ImGuiMod_Ctrl | ImGuiMod_Shift | ImGuiKey_Z, ImGuiInputFlags_RouteGlobal ) ||
		ImGui::Shortcut( ImGuiMod_Ctrl | ImGuiKey_Y, ImGuiInputFlags_RouteGlobal ) )
		Redo();
	if( ImGui::Shortcut( ImGuiMod_Ctrl | ImGuiKey_S, ImGuiInputFlags_RouteGlobal ) )
		SaveLevel( levelPath.empty() ? m_settings.levelsDir + "/" + m_saveName + ".level.json" : levelPath );
	if( ImGui::Shortcut( ImGuiMod_Ctrl | ImGuiKey_D, ImGuiInputFlags_RouteGlobal ) ) DuplicateSelected();
	if( io.WantTextInput ) return;   // typing in a field: the bare keys below are text
	if( ImGui::IsKeyPressed( ImGuiKey_Delete, false ) || ImGui::IsKeyPressed( ImGuiKey_Backspace, false ) ) DeleteSelected();
	if( !io.KeyCtrl && !io.KeyAlt && !io.KeySuper )
	{
		if( ImGui::IsKeyPressed( ImGuiKey_Q, false ) ) m_gizmoOp = 0;
		if( ImGui::IsKeyPressed( ImGuiKey_W, false ) ) m_gizmoOp = 1;
		if( ImGui::IsKeyPressed( ImGuiKey_E, false ) ) m_gizmoOp = 2;
		if( ImGui::IsKeyPressed( ImGuiKey_R, false ) ) m_gizmoOp = 3;
		if( ImGui::IsKeyPressed( ImGuiKey_F, false ) ) FrameSelected();
	}
}

void Editor::ViewportPanel( float dt )
{
	ImGui::PushStyleVar( ImGuiStyleVar_WindowPadding, ImVec2( 0, 0 ) );
	ImGui::Begin( "Viewport", nullptr, ImGuiWindowFlags_NoScrollbar | ImGuiWindowFlags_NoScrollWithMouse );
	ImGui::PopStyleVar();
	// tool strip
	ImGui::SetCursorPos( ImVec2( 6, ImGui::GetCursorPosY() + 4 ) );
	const char* ops[] = { "Select (Q)", "Move (W)", "Rotate (E)", "Scale (R)" };
	for( int i = 0; i < 4; ++i )
	{
		if( i ) ImGui::SameLine();
		if( ImGui::RadioButton( ops[i], m_gizmoOp == i ) ) m_gizmoOp = i;
	}
	ImGui::SameLine();
	ImGui::Checkbox( "Snap", &m_snap );
	ImGui::SameLine();
	ImGui::TextDisabled( "| Alt+LMB orbit  Alt+MMB pan  wheel zoom  F frame" );

	const ImVec2 avail = ImGui::GetContentRegionAvail();
	const ImVec2 origin = ImGui::GetCursorScreenPos();
	m_viewX = origin.x;
	m_viewY = origin.y;
	m_viewW = std::max( 16.0f, avail.x );
	m_viewH = std::max( 16.0f, avail.y );
	const float fbScale = ImGui::GetIO().DisplayFramebufferScale.x > 0 ? ImGui::GetIO().DisplayFramebufferScale.x : 1.0f;

	ImGui::InvisibleButton( "##viewport", ImVec2( m_viewW, m_viewH ),
							ImGuiButtonFlags_MouseButtonLeft | ImGuiButtonFlags_MouseButtonRight | ImGuiButtonFlags_MouseButtonMiddle );
	const bool hovered = ImGui::IsItemHovered();
	if( ImGui::IsItemActivated() ) ImGui::SetWindowFocus();

	if( Playing() )
	{
		GatherPlayInput( dt, hovered );
		if( m_play->Possessed() ) m_play->CameraEyeTarget( m_cam.eye, m_cam.target );
	}
	else
		ViewportNavigation( hovered, m_viewW, m_viewH, origin.x, origin.y );

	FrameInfo info;
	info.scene = &m_scene;
	info.play = m_play.get();
	info.camera = m_cam;
	info.selected = m_selected;
	info.clear = m_settings.clear;
	info.brushVisible = m_brushOn && m_brushHover;
	info.brushPos = m_brushPos;
	info.brushRadius = m_brush.radius;
	m_renderer.Render( int( m_viewW * fbScale ), int( m_viewH * fbScale ), info );

	ImDrawList* dl = ImGui::GetWindowDrawList();
	dl->AddImage( ImTextureRef( (ImTextureID)(intptr_t)m_renderer.ColorTexture() ), origin, ImVec2( origin.x + m_viewW, origin.y + m_viewH ), ImVec2( 0, 1 ), ImVec2( 1, 0 ) );
	if( Playing() ) dl->AddRect( origin, ImVec2( origin.x + m_viewW, origin.y + m_viewH ), IM_COL32( 60, 220, 130, 255 ), 0.0f, 0, 3.0f );

	// move / rotate / scale handles on the selection (ImGuizmo uses the same S * Rx * Ry * Rz * T order as world::Transform)
	world::Entity* sel = m_scene.Find( m_selected );
	static bool wasUsing = false;
	if( sel && !Playing() && m_gizmoOp > 0 )
	{
		ImGuizmo::SetOrthographic( false );
		ImGuizmo::SetDrawlist( dl );
		ImGuizmo::SetRect( origin.x, origin.y, m_viewW, m_viewH );
		const Matrix view = m_cam.View(), proj = m_cam.Projection( m_viewW / m_viewH );
		float matrix[16];
		Vector3& p = sel->transform.position;
		Vector3& r = sel->transform.rotation;
		Vector3& s = sel->transform.scale;
		ImGuizmo::RecomposeMatrixFromComponents( &p.x, &r.x, &s.x, matrix );
		const ImGuizmo::OPERATION op = m_gizmoOp == 1 ? ImGuizmo::TRANSLATE : m_gizmoOp == 2 ? ImGuizmo::ROTATE : ImGuizmo::SCALE;
		const float snapMove[3] = { 1, 1, 1 }, snapRot[3] = { 15, 15, 15 }, snapScale[3] = { 0.25f, 0.25f, 0.25f };
		const float* snap = !m_snap ? nullptr : m_gizmoOp == 1 ? snapMove : m_gizmoOp == 2 ? snapRot : snapScale;
		if( sel->type == ActorType::Terrain && op != ImGuizmo::TRANSLATE ) {}   // terrain: move only
		else if( ImGuizmo::Manipulate( &view._11, &proj._11, op, ImGuizmo::LOCAL, matrix, nullptr, snap ) )
			ImGuizmo::DecomposeMatrixToComponents( matrix, &p.x, &r.x, &s.x );
		const bool using_ = ImGuizmo::IsUsing();
		if( wasUsing && !using_ ) Commit( "Transform" );
		wasUsing = using_;
		m_gizmoHover = ImGuizmo::IsOver() || using_;
	}
	else
	{
		wasUsing = false;
		m_gizmoHover = false;
	}
	ImGui::End();
}

void Editor::ViewportNavigation( bool hovered, float w, float h, float ox, float oy )
{
	ImGuiIO& io = ImGui::GetIO();
	const ImVec2 m = io.MousePos;
	const float mx = m.x - ox, my = m.y - oy;
	// Maya: Alt + left orbit, Alt + middle pan, Alt + right dolly; the wheel zooms
	static int navButton = -1;
	if( hovered && io.KeyAlt )
		for( int b = 0; b < 3; ++b )
			if( ImGui::IsMouseClicked( b ) ) navButton = b;
	if( navButton >= 0 && !ImGui::IsMouseDown( navButton ) ) navButton = -1;
	if( navButton >= 0 )
	{
		const ImVec2 d = io.MouseDelta;
		if( navButton == 0 )
		{
			m_yaw -= d.x * 0.006f;
			m_pitch = std::max( -1.5f, std::min( 1.5f, m_pitch - d.y * 0.006f ) );
		}
		else if( navButton == 2 )
		{
			const Vector3 fwd = Normalize( m_cam.target - m_cam.eye ), right = Normalize( Cross( fwd, Vector3( 0, 1, 0 ) ) ), up = Cross( right, fwd );
			const float k = m_dist * 0.0015f;
			m_pivot = m_pivot - right * ( d.x * k ) + up * ( d.y * k );
		}
		else
			m_dist = std::max( 1.0f, m_dist * ( 1.0f - ( d.x + d.y ) * 0.005f ) );
	}
	if( hovered && io.MouseWheel != 0.0f ) m_dist = std::max( 1.0f, m_dist * ( io.MouseWheel > 0 ? 0.88f : 1.0f / 0.88f ) );
	OrbitFromAngles();

	// brush hover + painting, or click-to-select
	Vector3 o, d;
	m_cam.Ray( mx, my, w, h, o, d );
	m_brushHover = false;
	if( m_brushOn && hovered && navButton < 0 )
	{
		Vector3 hit;
		uint32_t tid = 0;
		if( m_scene.RaycastTerrain( o, d, hit, &tid ) )
		{
			m_brushHover = true;
			m_brushPos = hit;
			if( ImGui::IsMouseClicked( 0 ) && !io.KeyAlt )
			{
				m_brushDragging = true;
				m_brushTerrain = tid;
				if( m_brush.mode == world::Brush::Flatten ) m_brush.flattenHeight = hit.y;
			}
			if( m_brushDragging && ImGui::IsMouseDown( 0 ) ) Sculpt( hit );
		}
	}
	if( m_brushDragging && !ImGui::IsMouseDown( 0 ) )
	{
		m_brushDragging = false;
		Commit( "Sculpt" );
	}
	const bool overGizmo = m_gizmoHover && m_scene.Find( m_selected ) && m_gizmoOp > 0;   // a handle is drawn and under the mouse
	if( !m_brushOn && hovered && !io.KeyAlt && ImGui::IsMouseClicked( 0 ) && !overGizmo )
		m_selected = m_scene.Pick( o, d );
}

void Editor::GatherPlayInput( float dt, bool hovered )
{
	(void)dt;
	ImGuiIO& io = ImGui::GetIO();
	world::PlayInput in = m_injected;
	const bool keys = ImGui::IsWindowFocused() || hovered;
	if( keys && !io.WantTextInput )
	{
		in.forward |= ImGui::IsKeyDown( ImGuiKey_W ) || ImGui::IsKeyDown( ImGuiKey_UpArrow );
		in.back |= ImGui::IsKeyDown( ImGuiKey_S ) || ImGui::IsKeyDown( ImGuiKey_DownArrow );
		in.turnLeft |= ImGui::IsKeyDown( ImGuiKey_A ) || ImGui::IsKeyDown( ImGuiKey_LeftArrow );
		in.turnRight |= ImGui::IsKeyDown( ImGuiKey_D ) || ImGui::IsKeyDown( ImGuiKey_RightArrow );
		in.strafeLeft |= ImGui::IsKeyDown( ImGuiKey_Q );
		in.strafeRight |= ImGui::IsKeyDown( ImGuiKey_E );
		in.jump |= ImGui::IsKeyDown( ImGuiKey_Space );
		in.run |= io.KeyShift;
	}
	static bool turning = false, orbiting = false;
	if( hovered && ImGui::IsMouseClicked( 1 ) ) turning = true;
	if( hovered && ImGui::IsMouseClicked( 0 ) ) orbiting = true;
	if( !ImGui::IsMouseDown( 1 ) ) turning = false;
	if( !ImGui::IsMouseDown( 0 ) ) orbiting = false;
	if( turning || orbiting )
	{
		in.turning |= turning;
		in.orbit |= orbiting && !turning;
		in.mouseDX += io.MouseDelta.x;
		in.mouseDY += io.MouseDelta.y;
	}
	if( hovered ) in.wheel += -io.MouseWheel;   // wheel up = closer
	m_play->Tick( ImGui::GetIO().DeltaTime, in );
	m_injected.mouseDX = m_injected.mouseDY = m_injected.wheel = 0;
}

// ------------------------------------------------------------------------------------------------ panels
void Editor::PlacePanel()
{
	ImGui::Begin( "Place Actors" );
	ImGui::TextDisabled( "Click to place where the viewport looks." );
	auto groupOf = []( ActorType t ) {
		return t == ActorType::Terrain || t == ActorType::CreatureSpawn || t == ActorType::PlayerStart ? 0
			   : t == ActorType::PointLight || t == ActorType::DirLight ? 2 : 1;
	};
	const char* groups[] = { "World", "Basic", "Lights" };
	ImGui::BeginDisabled( Playing() );
	for( int g = 0; g < 3; ++g )
	{
		ImGui::SeparatorText( groups[g] );
		for( const auto& a : world::Actors() )
		{
			if( groupOf( a.type ) != g ) continue;
			if( ImGui::Button( a.label, ImVec2( -1, 0 ) ) ) Place( a.type, PlacementPoint() );
			ImGui::SetItemTooltip( "%s", a.what );
		}
	}
	ImGui::EndDisabled();
	ImGui::End();
}

void Editor::OutlinerPanel()
{
	ImGui::Begin( "Outliner" );
	const auto& list = Playing() ? m_play->World().Entities() : m_scene.Entities();
	for( const auto& e : list )
	{
		ImGui::PushID( int( e.id ) );
		const std::string label = e.name + "  ##" + std::to_string( e.id );
		ImGui::BeginDisabled( !e.visible );
		if( ImGui::Selectable( label.c_str(), e.id == m_selected ) ) m_selected = e.id;
		ImGui::EndDisabled();
		if( ImGui::IsItemHovered() && ImGui::IsMouseDoubleClicked( 0 ) ) FrameSelected();
		ImGui::SameLine( ImGui::GetContentRegionAvail().x * 0.62f );
		ImGui::TextDisabled( "%s", world::InfoOf( e.type ).label );
		ImGui::PopID();
	}
	if( Playing() )
	{
		ImGui::SeparatorText( "Play" );
		for( const auto& c : m_play->Creatures() )
			ImGui::TextColored( c.state == world::Creature::Chase ? ImVec4( 1, 0.4f, 0.35f, 1 ) : ImVec4( 0.7f, 0.7f, 0.7f, 1 ), "%s  %s", c.name.c_str(),
								c.state == world::Creature::Chase ? "(attacking)" : c.state == world::Creature::Return ? "(going home)" : "" );
	}
	ImGui::End();
}

void Editor::DetailsPanel()
{
	ImGui::Begin( "Details" );
	world::Entity* e = Playing() ? nullptr : m_scene.Find( m_selected );
	if( Playing() ) ImGui::TextDisabled( "Stop playing to edit." );
	else if( !e ) ImGui::TextDisabled( "Select an actor in the viewport or the Outliner." );
	else
	{
		bool changed = false, done = false;
		char name[128];
		std::snprintf( name, sizeof( name ), "%s", e->name.c_str() );
		ImGui::TextDisabled( "%s", world::InfoOf( e->type ).label );
		if( ImGui::InputText( "Name", name, sizeof( name ) ) ) { e->name = name; changed = true; }
		done |= ImGui::IsItemDeactivatedAfterEdit();
		if( ImGui::Checkbox( "Visible", &e->visible ) ) done = true;
		ImGui::SeparatorText( "Transform" );
		ImGui::DragFloat3( "Location", &e->transform.position.x, 0.1f );
		done |= ImGui::IsItemDeactivatedAfterEdit();
		if( e->type != ActorType::Terrain )
		{
			ImGui::DragFloat3( "Rotation", &e->transform.rotation.x, 0.5f );
			done |= ImGui::IsItemDeactivatedAfterEdit();
			ImGui::DragFloat3( "Scale", &e->transform.scale.x, 0.02f, 0.01f, 1000.0f );
			done |= ImGui::IsItemDeactivatedAfterEdit();
		}
		ImGui::SeparatorText( world::InfoOf( e->type ).label );
		if( e->type == ActorType::Mesh )
		{
			std::string shape = e->props.value( "shape", std::string( "cube" ) );
			if( ImGui::BeginCombo( "Shape", shape.c_str() ) )
			{
				for( const char* s : kShapes )
					if( ImGui::Selectable( s, shape == s ) ) { e->props["shape"] = s; done = true; }
				ImGui::EndCombo();
			}
		}
		for( auto it = e->props.begin(); it != e->props.end(); ++it )
		{
			const std::string key = it.key();
			if( key == "shape" ) continue;
			auto& v = it.value();
			ImGui::PushID( key.c_str() );
			if( v.is_boolean() )
			{
				bool b = v.get<bool>();
				if( ImGui::Checkbox( key.c_str(), &b ) ) { v = b; done = true; }
			}
			else if( v.is_number_integer() )
			{
				int i = v.get<int>();
				if( ImGui::DragInt( key.c_str(), &i, 0.1f, 0, 1000 ) ) v = i;
				done |= ImGui::IsItemDeactivatedAfterEdit();
			}
			else if( v.is_number() )
			{
				float f = v.get<float>();
				if( ImGui::DragFloat( key.c_str(), &f, 0.05f ) ) v = f;
				done |= ImGui::IsItemDeactivatedAfterEdit();
			}
			else if( v.is_string() && v.get<std::string>().size() == 7 && v.get<std::string>()[0] == '#' )
			{
				Vector3 c = world::HexColor( v.get<std::string>() );
				if( ImGui::ColorEdit3( key.c_str(), &c.x ) ) v = world::ToHex( c );
				done |= ImGui::IsItemDeactivatedAfterEdit();
			}
			else if( v.is_string() )
			{
				char buf[256];
				std::snprintf( buf, sizeof( buf ), "%s", v.get<std::string>().c_str() );
				if( ImGui::InputText( key.c_str(), buf, sizeof( buf ) ) ) v = std::string( buf );
				done |= ImGui::IsItemDeactivatedAfterEdit();
			}
			else if( v.is_array() && v.size() == 3 )
			{
				float a[3] = { v[0].get<float>(), v[1].get<float>(), v[2].get<float>() };
				if( ImGui::DragFloat3( key.c_str(), a, 0.05f ) ) v = { a[0], a[1], a[2] };
				done |= ImGui::IsItemDeactivatedAfterEdit();
			}
			ImGui::PopID();
		}
		if( e->type == ActorType::Terrain && e->terrain )
			ImGui::TextDisabled( "%d x %d grid over %.0f m. Sculpt it in the Terrain panel.", e->terrain->Res(), e->terrain->Res(), e->terrain->Size() );
		ImGui::Spacing();
		if( ImGui::Button( "Duplicate" ) ) DuplicateSelected();
		ImGui::SameLine();
		if( ImGui::Button( "Delete" ) ) DeleteSelected();
		if( done || changed ) Commit( "Edit" );
	}
	ImGui::End();
}

void Editor::TerrainPanel()
{
	ImGui::Begin( "Terrain" );
	ImGui::BeginDisabled( Playing() );
	if( ImGui::Checkbox( "Sculpt / paint with the mouse", &m_brushOn ) && m_brushOn )
	{
		bool any = false;
		for( const auto& e : m_scene.Entities() ) any |= e.type == ActorType::Terrain;
		if( !any ) Place( ActorType::Terrain, Vector3( 0, 0, 0 ) );
	}
	const char* modes[] = { "Raise", "Lower", "Smooth", "Flatten", "Paint" };
	int mode = int( m_brush.mode );
	for( int i = 0; i < 5; ++i )
	{
		if( i ) ImGui::SameLine();
		if( ImGui::RadioButton( modes[i], mode == i ) ) { m_brush.mode = world::Brush::Mode( i ); m_brushOn = true; }
	}
	ImGui::SliderFloat( "Radius", &m_brush.radius, 0.5f, 40.0f, "%.1f m" );
	ImGui::SliderFloat( "Strength", &m_brush.strength, 0.02f, 2.0f );
	ImGui::SeparatorText( "Paint" );
	for( const auto& p : kPaints )
	{
		ImGui::PushID( p.name );
		if( ImGui::ColorButton( p.name, Col( p.rgb ), 0, ImVec2( 28, 22 ) ) )
		{
			m_brush.color = p.rgb;
			m_brush.mode = world::Brush::Paint;
			m_brushOn = true;
		}
		ImGui::SetItemTooltip( "%s", p.name );
		ImGui::SameLine();
		ImGui::PopID();
	}
	ImGui::ColorEdit3( "##paint", &m_brush.color.x, ImGuiColorEditFlags_NoInputs );
	ImGui::TextDisabled( "Drag in the viewport. Alt still orbits the camera." );
	ImGui::EndDisabled();
	ImGui::End();
}

void Editor::LevelsPanel()
{
	ImGui::Begin( "Levels" );
	ImGui::SetNextItemWidth( 180 );
	ImGui::InputText( "##name", m_saveName, sizeof( m_saveName ) );
	ImGui::SameLine();
	if( ImGui::Button( "Save As" ) ) SaveLevel( m_settings.levelsDir + "/" + m_saveName + ".level.json" );
	ImGui::SameLine();
	ImGui::TextDisabled( "%s", levelPath.empty() ? "(unsaved)" : levelPath.c_str() );
	ImGui::Separator();
	std::error_code ec;
	if( fs::is_directory( m_settings.levelsDir, ec ) )
	{
		for( const auto& f : fs::directory_iterator( m_settings.levelsDir, ec ) )
		{
			const std::string p = f.path().string();
			if( p.size() < 11 || p.compare( p.size() - 11, 11, ".level.json" ) != 0 ) continue;
			if( ImGui::Selectable( f.path().filename().string().c_str(), p == levelPath ) ) OpenLevel( p );
		}
	}
	else
		ImGui::TextDisabled( "No levels yet in %s - Save As makes the first one.", m_settings.levelsDir.c_str() );
	ImGui::End();
}

void Editor::OutputPanel()
{
	ImGui::Begin( "Output" );
	for( const auto& line : m_log ) ImGui::TextUnformatted( line.c_str() );
	if( ImGui::GetScrollY() >= ImGui::GetScrollMaxY() - 4 ) ImGui::SetScrollHereY( 1.0f );
	ImGui::End();
}
}
