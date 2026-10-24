// MODULE: render
// Renderer abstraction. The engine only talks to IRenderer; backends are chosen
// by name at startup. To plug in Carbon's Trinity (or any custom renderer),
// implement IRenderer and register it in RendererFactory.cpp - nothing else changes.
#pragma once

#include <functional>
#include <memory>
#include <string>
#include <vector>

namespace cmmo
{
struct Color
{
	float r = 0.0f, g = 0.0f, b = 0.0f, a = 1.0f;
};

// Filled in by the Python init hook (scripts/init_render.py) before the renderer starts,
// and readable/writable from Python every frame.
struct RenderConfig
{
	std::string title = "Carbon MMO";
	int width = 1280;
	int height = 720;
	Color clear_color{ 0.05f, 0.06f, 0.09f, 1.0f };
	bool vsync = true;
	int max_frames = 0; // 0 = until the window closes (null renderer treats 0 as 3)

	// Returns human-readable problems; empty means valid.
	std::vector<std::string> Validate() const;
};

// Called once per frame; return false to stop the loop.
using FrameCallback = std::function<bool( int frame_index, double dt_seconds )>;

class IRenderer
{
public:
	virtual ~IRenderer() = default;
	virtual const char* Name() const = 0;
	virtual bool Init( RenderConfig& config ) = 0;
	// Runs the frame loop; `config` is re-read every frame so scripts can change it live.
	virtual int Run( RenderConfig& config, const FrameCallback& on_frame ) = 0;
	virtual void Shutdown() = 0;
};

std::unique_ptr<IRenderer> CreateRenderer( const std::string& backend );
std::vector<std::string> AvailableRenderers();
}
