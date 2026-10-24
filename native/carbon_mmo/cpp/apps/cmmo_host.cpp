// MODULE: app
// Phase 1 entry point: C++ host -> Python init hook -> renderer.
//
//   cmmo_host [--script scripts/init_render.py] [--renderer null|glfw] [--frames N]
//
// Prints "PHASE1 OK" and exits 0 when the round trip worked.
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>

#include "render/Renderer.h"
#include "script_host/ScriptHost.h"

int main( int argc, char** argv )
{
	std::string script = std::string( CMMO_SOURCE_DIR ) + "/scripts/init_render.py";
	std::string backend = "null";
	int frames_override = -1;

	for( int i = 1; i < argc; ++i )
	{
		if( !std::strcmp( argv[i], "--script" ) && i + 1 < argc )
		{
			script = argv[++i];
		}
		else if( !std::strcmp( argv[i], "--renderer" ) && i + 1 < argc )
		{
			backend = argv[++i];
		}
		else if( !std::strcmp( argv[i], "--frames" ) && i + 1 < argc )
		{
			frames_override = std::atoi( argv[++i] );
		}
		else
		{
			std::printf( "usage: %s [--script path] [--renderer null|glfw] [--frames N]\n", argv[0] );
			return 2;
		}
	}

	cmmo::RenderConfig config;
	int frames_rendered = 0;
	int py_to_cpp = 0;
	int cpp_to_py = 0;
	{
		cmmo::ScriptHost host( argv[0] );

		std::string error;
		if( !host.RunInitHook( script, config, error ) )
		{
			std::fprintf( stderr, "[host] init hook failed: %s\n", error.c_str() );
			return 1;
		}
		if( frames_override >= 0 )
		{
			config.max_frames = frames_override;
		}
		std::printf( "[host] config from Python: %dx%d \"%s\" clear=(%.3f, %.3f, %.3f)\n",
					 config.width, config.height, config.title.c_str(),
					 config.clear_color.r, config.clear_color.g, config.clear_color.b );

		auto renderer = cmmo::CreateRenderer( backend );
		if( !renderer )
		{
			std::fprintf( stderr, "[host] unknown renderer '%s'\n", backend.c_str() );
			return 1;
		}
		if( !renderer->Init( config ) )
		{
			// A machine without a display must never crash the engine: fall back.
			std::fprintf( stderr, "[host] renderer '%s' failed to start, falling back to null\n", backend.c_str() );
			renderer->Shutdown();
			renderer = cmmo::CreateRenderer( "null" );
			renderer->Init( config );
		}
		frames_rendered = renderer->Run( config, [&host]( int frame, double dt ) { return host.CallFrame( frame, dt ); } );
		renderer->Shutdown();

		py_to_cpp = host.PythonToCppCallCount();
		cpp_to_py = host.CppToPythonCallCount();
	}

	std::printf( "[host] frames=%d  python->c++ calls=%d  c++->python calls=%d\n", frames_rendered, py_to_cpp, cpp_to_py );
	if( frames_rendered > 0 && py_to_cpp > 0 && cpp_to_py > 1 )
	{
		std::printf( "PHASE1 OK\n" );
		return 0;
	}
	std::printf( "PHASE1 FAILED (binding round trip incomplete)\n" );
	return 1;
}
