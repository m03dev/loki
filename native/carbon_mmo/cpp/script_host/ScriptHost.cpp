// MODULE: script-host
#include "script_host/ScriptHost.h"

#include <pybind11/embed.h>
#include <pybind11/stl.h>

#include <cstdio>
#include <cstdlib>

#include "script_host/EngineModule.h"

namespace py = pybind11;

namespace cmmo
{
namespace
{
std::unique_ptr<py::scoped_interpreter> StartInterpreter( const std::string& program_path )
{
	PyConfig config;
	PyConfig_InitPythonConfig( &config );
	config.parse_argv = 0;
	config.install_signal_handlers = 1;
	// Point the interpreter at the Python we were built against, unless the user
	// overrides it. Without this an exe living in build/bin can't find the stdlib.
	const char* env_home = std::getenv( "PYTHONHOME" );
	if( !env_home || !*env_home )
	{
		PyConfig_SetBytesString( &config, &config.home, CMMO_PYTHON_HOME );
	}
	PyConfig_SetBytesString( &config, &config.program_name, program_path.c_str() );
	auto interpreter = std::make_unique<py::scoped_interpreter>( &config, 0, nullptr, false );
	PyConfig_Clear( &config );
	return interpreter;
}
}

ScriptHost::ScriptHost( const std::string& program_path )
	: m_interpreter( StartInterpreter( program_path ) )
{
	// Repo python/ (cmmo package) and build/python (cmmo_math extension).
	AddImportPath( std::string( CMMO_SOURCE_DIR ) + "/python" );
	AddImportPath( std::string( CMMO_BINARY_DIR ) + "/python" );
	py::module_::import( "cmmo_engine" ); // registers RenderConfig before any cast
}

ScriptHost::~ScriptHost()
{
	engine_module::Reset(); // release py objects while the interpreter is alive
	m_interpreter.reset();
}

void ScriptHost::AddImportPath( const std::string& path )
{
	py::module_::import( "sys" ).attr( "path" ).attr( "insert" )( 0, path );
}

bool ScriptHost::RunInitHook( const std::string& script_path, RenderConfig& config, std::string& error )
{
	try
	{
		py::dict globals = py::module_::import( "runpy" ).attr( "run_path" )( script_path );
		if( !globals.contains( "configure_render" ) )
		{
			error = script_path + " has no configure_render(cfg) function";
			return false;
		}
		++m_cppToPythonCalls;
		// Pass the C++ object by reference: Python edits the real config, not a copy.
		globals["configure_render"]( py::cast( &config, py::return_value_policy::reference ) );
	}
	catch( const py::error_already_set& e )
	{
		error = e.what();
		return false;
	}

	auto problems = config.Validate();
	if( !problems.empty() )
	{
		error = "invalid render config from script:";
		for( const auto& p : problems )
		{
			error += "\n  - " + p;
		}
		return false;
	}
	return true;
}

bool ScriptHost::CallFrame( int frame_index, double dt_seconds )
{
	py::object callback = engine_module::FrameCallback();
	if( callback.is_none() )
	{
		return true;
	}
	try
	{
		++m_cppToPythonCalls;
		py::object result = callback( frame_index, dt_seconds );
		return result.is_none() || result.cast<bool>();
	}
	catch( const py::error_already_set& e )
	{
		std::fprintf( stderr, "[script-host] on_frame raised, stopping loop:\n%s\n", e.what() );
		return false;
	}
}

int ScriptHost::PythonToCppCallCount() const
{
	return engine_module::PythonToCppCalls();
}
}
