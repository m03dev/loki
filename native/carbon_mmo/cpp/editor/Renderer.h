// MODULE: editor.render
// The editor's OpenGL 3.3 renderer: draws a world::Scene (terrain, shapes, actor markers, Play's player and
// creatures) into an offscreen framebuffer that the editor shows in its Viewport panel.
// Swap point: replace with Carbon Trinity or a Vulkan / Metal renderer - the editor only uses this interface.
#pragma once

#include <cstdint>
#include <map>
#include <string>
#include <vector>

#include "Matrix.h"
#include "Vector3.h"
#include "world/World.h"

namespace cmmo::editor
{
struct CameraView
{
	Vector3 eye{ 0, 10, 20 }, target{ 0, 0, 0 };
	float fovDeg = 55.0f, nearZ = 0.1f, farZ = 3000.0f;
	Matrix View() const;
	Matrix Projection( float aspect ) const;   // OpenGL clip space, right-handed
	// world-space ray through a viewport pixel (0..w, 0..h, y down)
	void Ray( float px, float py, float w, float h, Vector3& origin, Vector3& dir ) const;
};

struct FrameInfo
{
	const world::Scene* scene = nullptr;
	const world::PlaySession* play = nullptr;   // when playing: draws the player and creatures, hides editor markers
	CameraView camera;
	uint32_t selected = 0;
	bool grid = true;
	Vector3 clear{ 0.36f, 0.5f, 0.68f };
	bool brushVisible = false;
	Vector3 brushPos;
	float brushRadius = 1.0f;
};

class Renderer
{
public:
	bool Init( std::string& error );
	void Shutdown();
	void Render( int width, int height, const FrameInfo& frame );
	unsigned ColorTexture() const { return m_color; }
	int Width() const { return m_w; }
	int Height() const { return m_h; }
	// RGBA rows, top row first (for screenshots and tests)
	std::vector<uint8_t> ReadPixels() const;
	int DrawCalls() const { return m_drawCalls; }

	struct Mesh
	{
		unsigned vao = 0, vbo = 0, ibo = 0;
		int count = 0;
		unsigned prim = 0;
	};

private:
	void EnsureTarget( int w, int h );
	void Draw( const Mesh& mesh, const Matrix& world, const Vector3& tint, bool vertexColor, bool unlit, float alpha = 1.0f );
	Mesh& TerrainMesh( const world::Entity& e );

	unsigned m_program = 0, m_fbo = 0, m_color = 0, m_depth = 0;
	int m_w = 0, m_h = 0;
	int m_drawCalls = 0;
	Matrix m_viewProj;
	std::map<std::string, Mesh> m_meshes;
	struct TerrainGpu
	{
		Mesh mesh;
		uint32_t version = 0;
		const world::Terrain* source = nullptr;
	};
	std::map<uint32_t, TerrainGpu> m_terrains;
	int u_mvp = -1, u_model = -1, u_tint = -1, u_vcol = -1, u_unlit = -1, u_alpha = -1, u_sunDir = -1, u_sunCol = -1,
		u_ambient = -1, u_nPoints = -1, u_pointPos = -1, u_pointCol = -1, u_pointRange = -1, u_eye = -1, u_fog = -1,
		u_fogDensity = -1;
};
}
