// MODULE: script-host
// The `cmmo_engine` module that exists only inside the embedded interpreter.
#include "script_host/EngineModule.h"

#include <pybind11/embed.h>
#include <pybind11/stl.h>

#include <cstdio>
#include <string>

#include "math/CarbonMathBindings.h"
#include "render/Renderer.h"

namespace py = pybind11;

namespace
{
int g_pythonToCppCalls = 0;
py::object* g_frameCallback = nullptr; // heap-held so it can be released before finalize

float ParseHexByte( const std::string& hex, size_t at )
{
	return static_cast<float>( std::stoi( hex.substr( at, 2 ), nullptr, 16 ) ) / 255.0f;
}

cmmo::Color ToColor( const py::object& value )
{
	cmmo::Color c;
	if( py::isinstance<py::str>( value ) )
	{
		std::string hex = value.cast<std::string>();
		if( !hex.empty() && hex[0] == '#' )
		{
			hex = hex.substr( 1 );
		}
		if( hex.size() != 6 && hex.size() != 8 )
		{
			throw py::value_error( "clear_color hex must be #RRGGBB or #RRGGBBAA" );
		}
		c.r = ParseHexByte( hex, 0 );
		c.g = ParseHexByte( hex, 2 );
		c.b = ParseHexByte( hex, 4 );
		c.a = hex.size() == 8 ? ParseHexByte( hex, 6 ) : 1.0f;
		return c;
	}
	py::sequence seq = value.cast<py::sequence>();
	if( seq.size() != 3 && seq.size() != 4 )
	{
		throw py::value_error( "clear_color needs 3 or 4 floats in [0, 1]" );
	}
	c.r = seq[0].cast<float>();
	c.g = seq[1].cast<float>();
	c.b = seq[2].cast<float>();
	c.a = seq.size() == 4 ? seq[3].cast<float>() : 1.0f;
	return c;
}
}

namespace cmmo::engine_module
{
int PythonToCppCalls()
{
	return g_pythonToCppCalls;
}

py::object FrameCallback()
{
	return g_frameCallback ? *g_frameCallback : py::none();
}

void Reset()
{
	delete g_frameCallback;
	g_frameCallback = nullptr;
}
}

PYBIND11_EMBEDDED_MODULE( cmmo_engine, m )
{
	using cmmo::RenderConfig;
	m.doc() = "Engine services exposed by the C++ host to Python scripts";

	py::class_<RenderConfig>( m, "RenderConfig" )
		.def_readwrite( "title", &RenderConfig::title )
		.def_readwrite( "width", &RenderConfig::width )
		.def_readwrite( "height", &RenderConfig::height )
		.def_readwrite( "vsync", &RenderConfig::vsync )
		.def_readwrite( "max_frames", &RenderConfig::max_frames )
		.def_property(
			"clear_color",
			[]( const RenderConfig& c ) {
				return py::make_tuple( c.clear_color.r, c.clear_color.g, c.clear_color.b, c.clear_color.a );
			},
			[]( RenderConfig& c, const py::object& v ) {
				++g_pythonToCppCalls;
				c.clear_color = ToColor( v );
			} )
		.def( "validate",
			  []( const RenderConfig& c ) {
				  ++g_pythonToCppCalls;
				  return c.Validate();
			  } )
		.def( "__repr__", []( const RenderConfig& c ) {
			char buf[160];
			std::snprintf( buf, sizeof( buf ), "RenderConfig(%dx%d, clear=(%.2f, %.2f, %.2f, %.2f))",
						   c.width, c.height, c.clear_color.r, c.clear_color.g, c.clear_color.b, c.clear_color.a );
			return std::string( buf );
		} );

	m.def( "log", []( const std::string& message ) {
		++g_pythonToCppCalls;
		std::printf( "[py] %s\n", message.c_str() );
		std::fflush( stdout );
	} );

	m.def( "info", []() {
		++g_pythonToCppCalls;
		py::dict d;
		d["engine"] = "carbon-mmo";
		d["version"] = "0.1.0";
		d["renderers"] = cmmo::AvailableRenderers();
#if defined( _WIN32 )
		d["platform"] = "windows";
#elif defined( __APPLE__ )
		d["platform"] = "macos";
#else
		d["platform"] = "linux";
#endif
		return d;
	} );

	m.def(
		"on_frame",
		[]( py::function fn ) {
			++g_pythonToCppCalls;
			cmmo::engine_module::Reset();
			g_frameCallback = new py::object( fn );
			return fn; // usable as a decorator
		},
		"Register fn(frame_index, dt) -> bool|None, called by C++ every frame" );

	cmmo::BindCarbonMath( m ); // the same Carbon Vector3 the cmmo_math extension exposes
}
