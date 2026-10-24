// MODULE: render
// The only place that knows which renderer backends exist.
#include "render/Renderer.h"

namespace cmmo
{
std::unique_ptr<IRenderer> CreateNullRenderer();
#ifdef CMMO_WITH_GLFW
std::unique_ptr<IRenderer> CreateGlfwRenderer();
#endif

std::unique_ptr<IRenderer> CreateRenderer( const std::string& backend )
{
#ifdef CMMO_WITH_GLFW
	if( backend == "glfw" || backend == "window" )
	{
		return CreateGlfwRenderer();
	}
#endif
	if( backend == "null" || backend == "headless" )
	{
		return CreateNullRenderer();
	}
	return nullptr;
}

std::vector<std::string> AvailableRenderers()
{
	std::vector<std::string> names{ "null" };
#ifdef CMMO_WITH_GLFW
	names.push_back( "glfw" );
#endif
	return names;
}
}
