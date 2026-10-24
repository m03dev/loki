// MODULE: render
// Minimal windowed backend: GLFW window + OpenGL clear. It exists to prove the
// Python-configured window size / background color reach a real window without
// crashing. Replace with Carbon Trinity or a custom renderer via RendererFactory.
#include "render/Renderer.h"

#include <chrono>
#include <cstdio>

#define GL_SILENCE_DEPRECATION
#include <GLFW/glfw3.h>

namespace cmmo
{
namespace
{
void OnGlfwError( int code, const char* message )
{
	std::fprintf( stderr, "[render:glfw] error %d: %s\n", code, message );
}
}

class GlfwRenderer final : public IRenderer
{
public:
	const char* Name() const override { return "glfw"; }

	bool Init( RenderConfig& config ) override
	{
		glfwSetErrorCallback( OnGlfwError );
		if( !glfwInit() )
		{
			return false;
		}
		m_initialized = true;
#ifdef __APPLE__
		glfwWindowHint( GLFW_COCOA_RETINA_FRAMEBUFFER, GLFW_TRUE );
#endif
		m_window = glfwCreateWindow( config.width, config.height, config.title.c_str(), nullptr, nullptr );
		if( !m_window )
		{
			return false;
		}
		glfwMakeContextCurrent( m_window );
		glfwSwapInterval( config.vsync ? 1 : 0 );
		std::printf( "[render:glfw] window %dx%d \"%s\"\n", config.width, config.height, config.title.c_str() );
		return true;
	}

	int Run( RenderConfig& config, const FrameCallback& on_frame ) override
	{
		int frame = 0;
		auto last = std::chrono::steady_clock::now();
		while( !glfwWindowShouldClose( m_window ) )
		{
			if( config.max_frames > 0 && frame >= config.max_frames )
			{
				break;
			}
			auto now = std::chrono::steady_clock::now();
			double dt = std::chrono::duration<double>( now - last ).count();
			last = now;
			if( on_frame && !on_frame( frame, dt ) )
			{
				++frame;
				break;
			}
			int fbw = 0, fbh = 0;
			glfwGetFramebufferSize( m_window, &fbw, &fbh );
			glViewport( 0, 0, fbw, fbh );
			glClearColor( config.clear_color.r, config.clear_color.g, config.clear_color.b, config.clear_color.a );
			glClear( GL_COLOR_BUFFER_BIT );
			glfwSwapBuffers( m_window );
			glfwPollEvents();
			++frame;
		}
		return frame;
	}

	void Shutdown() override
	{
		if( m_window )
		{
			glfwDestroyWindow( m_window );
			m_window = nullptr;
		}
		if( m_initialized )
		{
			glfwTerminate();
			m_initialized = false;
		}
		std::printf( "[render:glfw] shutdown\n" );
	}

private:
	GLFWwindow* m_window = nullptr;
	bool m_initialized = false;
};

std::unique_ptr<IRenderer> CreateGlfwRenderer()
{
	return std::make_unique<GlfwRenderer>();
}
}
