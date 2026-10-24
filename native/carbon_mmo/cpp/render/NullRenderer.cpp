// MODULE: render
// Headless backend: no window, no GPU. Used by CI and dedicated servers, and as the
// safe fallback whenever a windowed backend can't start.
#include "render/Renderer.h"

#include <chrono>
#include <cstdio>

namespace cmmo
{
class NullRenderer final : public IRenderer
{
public:
	const char* Name() const override { return "null"; }

	bool Init( RenderConfig& config ) override
	{
		std::printf( "[render:null] init %dx%d \"%s\" clear=(%.2f, %.2f, %.2f, %.2f)\n",
					 config.width, config.height, config.title.c_str(),
					 config.clear_color.r, config.clear_color.g, config.clear_color.b, config.clear_color.a );
		return true;
	}

	int Run( RenderConfig& config, const FrameCallback& on_frame ) override
	{
		const int frames = config.max_frames > 0 ? config.max_frames : 3;
		int rendered = 0;
		auto last = std::chrono::steady_clock::now();
		for( ; rendered < frames; ++rendered )
		{
			auto now = std::chrono::steady_clock::now();
			double dt = std::chrono::duration<double>( now - last ).count();
			last = now;
			if( on_frame && !on_frame( rendered, dt ) )
			{
				++rendered;
				break;
			}
			std::printf( "[render:null] frame %d clear=(%.2f, %.2f, %.2f)\n", rendered,
						 config.clear_color.r, config.clear_color.g, config.clear_color.b );
		}
		return rendered;
	}

	void Shutdown() override { std::printf( "[render:null] shutdown\n" ); }
};

std::unique_ptr<IRenderer> CreateNullRenderer()
{
	return std::make_unique<NullRenderer>();
}
}
