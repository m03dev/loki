// MODULE: script-host
// Embedded Python host and the C++ <-> Python pipeline.
//
// C++ -> Python : ScriptHost runs scripts/init_render.py, calls configure_render(cfg)
//                 and then the registered on_frame(frame, dt) callback every frame.
// Python -> C++ : the script mutates the C++ RenderConfig directly and calls
//                 cmmo_engine.log()/info()/Vector3 (all implemented in C++).
//
// Carbon's Blue (carbon-blue) is CCP's equivalent host: it embeds the interpreter,
// owns the game loop and exposes `blue` to Python. To switch to Blue, implement this
// class on top of Blue's exefile and keep exposing the same `cmmo_engine` module -
// the Python hook scripts stay unchanged.
#pragma once

#include <memory>
#include <string>

#include "render/Renderer.h"

namespace pybind11
{
class scoped_interpreter;
}

namespace cmmo
{
class ScriptHost
{
public:
	explicit ScriptHost( const std::string& program_path );
	~ScriptHost();

	ScriptHost( const ScriptHost& ) = delete;
	ScriptHost& operator=( const ScriptHost& ) = delete;

	void AddImportPath( const std::string& path );

	// Runs `script_path` and calls its configure_render(cfg). Returns false and fills
	// `error` on any Python exception or invalid config.
	bool RunInitHook( const std::string& script_path, RenderConfig& config, std::string& error );

	// Calls the script's on_frame callback if one was registered. Exceptions stop the
	// loop (logged) instead of crashing the host.
	bool CallFrame( int frame_index, double dt_seconds );

	int PythonToCppCallCount() const;
	int CppToPythonCallCount() const { return m_cppToPythonCalls; }

private:
	std::unique_ptr<pybind11::scoped_interpreter> m_interpreter;
	int m_cppToPythonCalls = 0;
};
}
