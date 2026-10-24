// MODULE: editor
// The Carbon MMO engine editor: a code-first game engine editor for a WoW-style online world - Unreal's toolbar and
// Play-in-Editor, Godot's scene tree and inspector, Terrain3D-style terrain tools, and an MMO gameplay layer
// (targeting, combat, quests, zones) you test with one key. The platform layer (apps/cmmo_editor.cpp: GLFW window or
// headless EGL) owns the window, the GL context and the ImGui backends, and calls Frame().
//
// Panels: Toolbar, Viewport (Maya navigation, Q/W/E/R gizmos, view cube, stats, Lit/Unlit/Wireframe, HUD in Play),
// Scene (tree, parenting by drag and drop, visibility, search), Inspector, Place Actors, Terrain, Content Browser
// (levels, models, prefabs), World Settings, Output.
#pragma once

#include <deque>
#include <memory>
#include <string>
#include <vector>

#include "editor/Renderer.h"
#include "world/World.h"

namespace cmmo::editor
{
struct EditorSettings
{
	std::string title = "Carbon MMO Editor";
	std::string contentDir = "content";   // levels/, models/, prefabs/
	std::string exePath;
};

class Editor
{
public:
	bool Init( const EditorSettings& settings, std::string& error );
	void Shutdown();
	void Frame( float dt );   // between ImGui::NewFrame() and ImGui::Render()
	bool WantsQuit() const { return m_quit; }

	// ---- actions (the UI, the hotkeys and the self-test all go through these)
	void NewLevel();                 // a sun, a Player Start and the grid - no terrain until you make one
	void NewStarterZone();           // a ready-to-play example: generated terrain, foliage, a camp, wolves, a quest
	bool SaveLevel( const std::string& path );
	bool OpenLevel( const std::string& path );
	uint32_t Place( world::ActorType type, const Vector3& at, uint32_t parent = 0 );
	uint32_t PlaceModel( const std::string& relPath, const Vector3& at );
	bool SavePrefab( uint32_t root, const std::string& name );
	uint32_t PlacePrefab( const std::string& relPath, const Vector3& at );
	void Select( uint32_t id ) { m_selected = id; }
	uint32_t Selected() const { return m_selected; }
	bool DeleteSelected();
	uint32_t DuplicateSelected();
	bool Reparent( uint32_t id, uint32_t parent );
	void Commit( const char* what );
	bool Undo();
	bool Redo();
	bool Play( bool possess );
	void Stop();
	bool Playing() const { return m_play != nullptr; }
	bool& Paused() { return m_paused; }
	world::PlaySession* Session() { return m_play.get(); }
	uint32_t CreateTerrain( float size, int res, bool generate );
	void BeginStroke( const Vector3& p );
	bool StrokeTo( const Vector3& p );   // one dab of the current tool on the terrain under the point
	void EndStroke();
	void FrameSelected();

	int& Tool() { return m_tool; }        // -1 = none, else world::Brush::Mode
	world::Brush& Brush() { return m_brush; }
	world::Scene& Scene() { return m_scene; }
	CameraView& Camera() { return m_cam; }
	Renderer& Render() { return m_renderer; }
	const std::vector<std::string>& Log() const { return m_log; }
	void Print( const std::string& line );
	world::PlayInput& InjectedInput() { return m_injected; }
	std::string ContentDir() const { return m_settings.contentDir; }
	float ViewOriginX() const { return m_viewX; }
	float ViewOriginY() const { return m_viewY; }
	float ViewW() const { return m_viewW; }
	float ViewH() const { return m_viewH; }

	std::string levelPath;

private:
	void MenuBar();
	void Toolbar( float height );
	void ViewportPanel( float dt );
	void ViewportOverlay( float ox, float oy );
	void Hud( float ox, float oy );
	void ScenePanel();
	void SceneNode( uint32_t id, const std::string& filter );
	void InspectorPanel();
	void PlacePanel();
	void TerrainPanel();
	void ContentPanel();
	void WorldPanel();
	void OutputPanel();
	void Navigation( bool hovered, float ox, float oy );
	void GatherPlayInput( bool hovered, float ox, float oy );
	void Hotkeys();
	void OrbitFromAngles();
	Vector3 PlacementPoint();
	Vector3 DropPoint( float mx, float my );

	EditorSettings m_settings;
	Renderer m_renderer;
	world::Scene m_scene;
	std::unique_ptr<world::PlaySession> m_play;
	bool m_paused = false;
	uint32_t m_selected = 0, m_renaming = 0;
	char m_renameBuf[128] = "";
	char m_filter[64] = "";
	CameraView m_cam;
	float m_yaw = 0.7f, m_pitch = -0.5f, m_dist = 60.0f;
	Vector3 m_pivot{ 0, 0, 0 };
	int m_gizmoOp = 1;   // 0 select, 1 move, 2 rotate, 3 scale
	bool m_local = true, m_snap = false, m_grid = true, m_stats = true;
	float m_snapMove = 1.0f;
	ViewMode m_viewMode = ViewMode::Lit;
	int m_tool = -1;
	world::Brush m_brush;
	bool m_stroke = false, m_brushHover = false, m_gizmoHover = false;
	Vector3 m_brushPos;
	int m_genSeed = 7;
	float m_genHeight = 28, m_genFeature = 40;
	int m_genOctaves = 5;
	int m_newSize = 1, m_newRes = 1;   // combo indices
	std::deque<std::string> m_undo, m_redo;
	std::string m_current;
	std::vector<std::string> m_log;
	world::PlayInput m_injected;
	bool m_quit = false, m_showDemo = false;
	float m_viewW = 1, m_viewH = 1, m_viewX = 0, m_viewY = 0;
	float m_fps = 60;
	int m_contentTab = 0;
	char m_saveName[128] = "my_level";
	char m_prefabName[128] = "prefab";
};
}
