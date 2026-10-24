// MODULE: editor.render
// The editor's OpenGL 3.3 renderer: draws a world::Scene into an offscreen framebuffer that the editor shows in its
// Viewport - sky dome, terrain (texture layers + auto-shader), batched foliage, shapes, glTF models, actor markers,
// and Play's player and creatures. View modes: Lit, Unlit, Wireframe.
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
	float fovDeg = 55.0f, nearZ = 0.1f, farZ = 4000.0f;
	Matrix View() const;
	Matrix Projection( float aspect ) const;   // OpenGL clip space, right-handed
	void Ray( float px, float py, float w, float h, Vector3& origin, Vector3& dir ) const;
	// world -> viewport pixels; false when behind the camera
	bool Project( const Vector3& p, float w, float h, float& sx, float& sy ) const;
};

enum class ViewMode
{
	Lit,
	Unlit,
	Wireframe
};

struct FrameInfo
{
	const world::Scene* scene = nullptr;
	const world::PlaySession* play = nullptr;   // when playing: draws the player and creatures, hides editor markers
	CameraView camera;
	uint32_t selected = 0;
	bool grid = true;
	ViewMode mode = ViewMode::Lit;
	bool brushVisible = false;
	Vector3 brushPos;
	float brushRadius = 1.0f;
	std::string contentDir;                     // where Model actors' paths are relative to
};

struct FrameStats
{
	int drawCalls = 0;
	int triangles = 0;
	int foliage = 0;
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
	std::vector<uint8_t> ReadPixels() const;   // RGBA rows, top first
	const FrameStats& Stats() const { return m_stats; }
	// load (and cache) a glTF / glb model; false + error when it can't be read
	bool ModelInfo( const std::string& path, int* triangles, std::string* error );

	struct Mesh
	{
		unsigned vao = 0, vbo = 0, ibo = 0;
		int count = 0;
		unsigned prim = 0;
		int triangles = 0;
	};

private:
	void EnsureTarget( int w, int h );
	void Draw( const Mesh& mesh, const Matrix& world, const Vector3& tint, bool vertexColor, bool unlit, float alpha = 1.0f );
	Mesh& TerrainMesh( const world::Entity& e );
	Mesh& FoliageMesh( const world::Entity& e );
	const Mesh* ModelMesh( const std::string& fullPath, std::string* error );

	unsigned m_program = 0, m_fbo = 0, m_color = 0, m_depth = 0;
	int m_w = 0, m_h = 0;
	FrameStats m_stats;
	ViewMode m_mode = ViewMode::Lit;
	Matrix m_viewProj;
	std::map<std::string, Mesh> m_meshes;
	struct TerrainGpu
	{
		Mesh mesh, foliage;
		uint32_t version = 0, shade = 0, foliageVersion = 0;
		const world::Terrain* source = nullptr;
	};
	std::map<uint32_t, TerrainGpu> m_terrains;
	struct ModelGpu
	{
		Mesh mesh;
		bool ok = false;
		std::string error;
	};
	std::map<std::string, ModelGpu> m_models;
	int u_mvp = -1, u_model = -1, u_tint = -1, u_vcol = -1, u_unlit = -1, u_alpha = -1, u_sunDir = -1, u_sunCol = -1,
		u_ambient = -1, u_nPoints = -1, u_pointPos = -1, u_pointCol = -1, u_pointRange = -1, u_eye = -1, u_fog = -1,
		u_fogDensity = -1, u_sky = -1, u_skyLow = -1;
};
}
