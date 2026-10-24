// MODULE: editor
// The Carbon MMO engine editor: a code-first level editor in the spirit of Unreal's, for a WoW-style world.
// Dear ImGui (docking) for the UI, ImGuizmo for move / rotate / scale handles, the editor.render module for the
// viewport, the world module for everything that is edited and played. The platform layer (apps/cmmo_editor.cpp:
// GLFW window or headless EGL) owns the window, the GL context and the ImGui backends, and calls Frame().
//
// Panels: Viewport (Maya navigation: Alt + left orbit, Alt + middle pan, Alt + right / wheel zoom, F frame;
// Q W E R select / move / rotate / scale), Outliner, Details, Place Actors, Terrain, Levels, Output.
// Play (Alt+P) / Simulate / Stop (Esc): Play runs on a copy of the level, so Stop always restores it.
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
	std::string levelsDir = "levels";
	Vector3 clear{ 0.36f, 0.5f, 0.68f };   // sky / viewport background (the Python init hook can change it)
};

class Editor
{
public:
	bool Init( const EditorSettings& settings, std::string& error );
	void Shutdown();
	// Build the UI and render the viewport. Call between ImGui::NewFrame() and ImGui::Render().
	void Frame( float dt );
	bool WantsQuit() const { return m_quit; }

	// ---- actions (the UI, the hotkeys and the self-test all go through these)
	void NewLevel();
	bool SaveLevel( const std::string& path );
	bool OpenLevel( const std::string& path );
	uint32_t Place( world::ActorType type, const Vector3& at );
	void Select( uint32_t id ) { m_selected = id; }
	uint32_t Selected() const { return m_selected; }
	bool DeleteSelected();
	uint32_t DuplicateSelected();
	void Commit( const char* what );            // record an undo step after a change
	bool Undo();
	bool Redo();
	bool Play( bool possess );
	void Stop();
	bool Playing() const { return m_play != nullptr; }
	world::PlaySession* Session() { return m_play.get(); }
	bool Sculpt( const Vector3& worldPoint );   // one dab of the current brush on the terrain under the point
	void FrameSelected();

	world::Scene& Scene() { return m_scene; }
	world::Brush& Brush() { return m_brush; }
	bool& BrushOn() { return m_brushOn; }
	CameraView& Camera() { return m_cam; }
	Renderer& Render() { return m_renderer; }
	const std::vector<std::string>& Log() const { return m_log; }
	void Print( const std::string& line );
	world::PlayInput& InjectedInput() { return m_injected; }   // headless tests drive Play through this
	float ViewOriginX() const { return m_viewX; }
	float ViewOriginY() const { return m_viewY; }
	float ViewW() const { return m_viewW; }
	float ViewH() const { return m_viewH; }

	std::string levelPath;

private:
	void MenuBar();
	void Toolbar();
	void ViewportPanel( float dt );
	void OutlinerPanel();
	void DetailsPanel();
	void PlacePanel();
	void TerrainPanel();
	void LevelsPanel();
	void OutputPanel();
	void ViewportNavigation( bool hovered, float w, float h, float ox, float oy );
	void GatherPlayInput( float dt, bool hovered );
	void Hotkeys();
	void OrbitFromAngles();
	Vector3 PlacementPoint();

	EditorSettings m_settings;
	Renderer m_renderer;
	world::Scene m_scene;
	std::unique_ptr<world::PlaySession> m_play;
	uint32_t m_selected = 0;
	CameraView m_cam;
	float m_yaw = 0.6f, m_pitch = -0.55f, m_dist = 60.0f;
	Vector3 m_pivot{ 0, 0, 0 };
	int m_gizmoOp = 1;   // 0 select, 1 move, 2 rotate, 3 scale
	bool m_snap = false;
	world::Brush m_brush;
	bool m_brushOn = false, m_brushDragging = false, m_brushHover = false;
	uint32_t m_brushTerrain = 0;
	Vector3 m_brushPos;
	std::deque<std::string> m_undo, m_redo;
	std::string m_current;   // the scene as last committed (JSON)
	std::vector<std::string> m_log;
	world::PlayInput m_injected;
	bool m_quit = false, m_showDemo = false, m_gizmoHover = false;   // gizmo hover from the frame it was drawn
	float m_viewW = 1, m_viewH = 1, m_viewX = 0, m_viewY = 0;
	char m_saveName[128] = "level1";
};
}
