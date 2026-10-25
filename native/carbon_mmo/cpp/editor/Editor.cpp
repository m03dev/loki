// MODULE: editor
#include "editor/Editor.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <cctype>
#include <cstring>
#include <map>
#include <random>
#include <set>

#include "editor/Theme.h"
#include "imgui.h"
#include "ImGuizmo.h"   // after imgui.h
#include "imgui_internal.h"

using cmmo::world::ActorType;
namespace fs = std::filesystem;

namespace cmmo::editor
{
namespace
{
constexpr float kPi = 3.14159265358979f;

const char* IconOf( ActorType t )
{
	switch( t )
	{
	case ActorType::Mesh: return ICON_FA_CUBE;
	case ActorType::PointLight: return ICON_FA_LIGHTBULB;
	case ActorType::DirLight: return ICON_FA_SUN;
	case ActorType::PlayerStart: return ICON_FA_PERSON;
	case ActorType::CreatureSpawn: return ICON_FA_DRAGON;
	case ActorType::TriggerBox: return ICON_FA_VECTOR_SQUARE;
	case ActorType::Terrain: return ICON_FA_MOUNTAIN_SUN;
	case ActorType::QuestGiver: return ICON_FA_SCROLL;
	case ActorType::Zone: return ICON_FA_MAP;
	case ActorType::Model: return ICON_FA_CHESS_ROOK;
	default: return ICON_FA_CIRCLE_DOT;
	}
}
ImU32 ColorOf( ActorType t )
{
	switch( t )
	{
	case ActorType::PointLight:
	case ActorType::DirLight: return IM_COL32( 245, 200, 90, 255 );
	case ActorType::PlayerStart: return IM_COL32( 90, 170, 255, 255 );
	case ActorType::CreatureSpawn: return IM_COL32( 235, 105, 90, 255 );
	case ActorType::Terrain: return IM_COL32( 120, 196, 110, 255 );
	case ActorType::QuestGiver:
	case ActorType::Zone: return IM_COL32( 240, 196, 70, 255 );
	case ActorType::Model: return IM_COL32( 190, 150, 240, 255 );
	default: return IM_COL32( 170, 178, 190, 255 );
	}
}
const char* AbilityIcon( const char* key )
{
	const std::string k = key;
	return k == "fist" ? ICON_FA_HAND_FIST : k == "bolt" ? ICON_FA_BOLT : k == "fire" ? ICON_FA_FIRE : k == "heart" ? ICON_FA_HEART : ICON_FA_STAR;
}

struct ToolDef
{
	world::Brush::Mode mode;
	const char* icon;
	const char* name;
	const char* what;
};
const ToolDef kTools[] = {
	{ world::Brush::Raise, ICON_FA_ARROW_TREND_UP, "Raise", "Drag to raise the ground. Hold the mouse for more." },
	{ world::Brush::Lower, ICON_FA_ARROW_TREND_DOWN, "Lower", "Drag to dig valleys and riverbeds." },
	{ world::Brush::Smooth, ICON_FA_WATER, "Smooth", "Drag to soften bumps and sharp edges." },
	{ world::Brush::Flatten, ICON_FA_RULER_HORIZONTAL, "Flatten", "Drag to level the ground to the height where you started - for camps and towns." },
	{ world::Brush::Ramp, ICON_FA_STAIRS, "Ramp", "Drag from one height to another to build a slope or a road up a hill." },
	{ world::Brush::Noise, ICON_FA_DICE, "Noise", "Drag to roughen the ground with natural-looking noise." },
	{ world::Brush::Paint, ICON_FA_PAINTBRUSH, "Paint", "Paint a texture layer (grass, dirt, rock, snow)." },
	{ world::Brush::Foliage, ICON_FA_TREE, "Foliage", "Scatter trees, pines, bushes, rocks or grass. They never grow on cliffs." },
	{ world::Brush::EraseFoliage, ICON_FA_ERASER, "Erase Foliage", "Remove the chosen foliage kind under the brush (Strength over 1: all kinds)." },
};

// "rewardXp" -> "Reward Xp", "levelMin" -> "Level Min"
std::string Pretty( const std::string& key )
{
	std::string out;
	for( size_t i = 0; i < key.size(); ++i )
	{
		const char c = key[i];
		if( i && std::isupper( (unsigned char)c ) ) out += ' ';
		out += i ? c : char( std::toupper( (unsigned char)c ) );
	}
	return out;
}

std::string ReadFile( const fs::path& p )
{
	std::ifstream f( p, std::ios::binary );
	return std::string( std::istreambuf_iterator<char>( f ), {} );
}
bool EndsWith( const std::string& s, const std::string& tail ) { return s.size() >= tail.size() && s.compare( s.size() - tail.size(), tail.size(), tail ) == 0; }
}

// ------------------------------------------------------------------------------------------------ lifecycle
bool Editor::Init( const EditorSettings& settings, std::string& error )
{
	m_settings = settings;
	if( !m_renderer.Init( error ) ) return false;
	std::error_code ec;
	for( const char* sub : { "levels", "models", "prefabs" } ) fs::create_directories( fs::path( m_settings.contentDir ) / sub, ec );
	NewLevel();
	Print( "Carbon Editor ready. File > New Starter Zone for a playable example; Alt+P plays, Esc stops." );
	return true;
}

void Editor::Shutdown()
{
	m_play.reset();
	m_renderer.Shutdown();
}

void Editor::Print( const std::string& line )
{
	m_log.push_back( line );
	if( m_log.size() > 600 ) m_log.erase( m_log.begin(), m_log.begin() + 100 );
	std::printf( "[editor] %s\n", line.c_str() );
	std::fflush( stdout );
}

// ------------------------------------------------------------------------------------------------ actions
void Editor::NewLevel()
{
	Stop();
	m_scene.Clear();
	world::Entity& sun = m_scene.Create( ActorType::DirLight );
	sun.transform.position = Vector3( 0, 30, 0 );
	sun.transform.rotation = Vector3( -48, 32, 0 );
	m_scene.Create( ActorType::PlayerStart ).transform.position = Vector3( 0, 0, 10 );
	m_selected = 0;
	m_undo.clear();
	m_redo.clear();
	m_current = m_scene.ToJson().dump();
	levelPath.clear();
	m_pivot = Vector3( 0, 0, 0 );
	m_dist = 45;
	m_yaw = 0.7f;
	m_pitch = -0.5f;
	OrbitFromAngles();
}

void Editor::NewStarterZone()
{
	NewLevel();
	m_scene.settings["name"] = "Greenhollow Vale";
	const uint32_t tid = m_scene.Create( ActorType::Terrain, "Greenhollow" ).id;
	world::Terrain& t = *m_scene.Find( tid )->terrain;
	t.Generate( 7, 26, 45, 5, false );
	world::Brush b;
	// a flat camp in the middle, a dirt road out to the wolf den
	b.mode = world::Brush::Flatten;
	b.radius = 14;
	b.strength = 1;
	b.height = t.HeightAt( 0, 0 );
	for( int k = 0; k < 6; ++k ) t.Sculpt( 0, 0, b );
	const float campY = t.HeightAt( 0, 0 );
	b.mode = world::Brush::Paint;
	b.layer = 1;
	b.radius = 3.5f;
	b.strength = 0.7f;
	for( float s = 0; s <= 1.0f; s += 0.02f ) t.Sculpt( 46 * s, -34 * s + 6 * std::sin( s * 6 ), b );
	b.radius = 9;
	t.Sculpt( 0, 0, b );
	// woods around the vale
	b.mode = world::Brush::Foliage;
	b.radius = 18;
	b.density = 0.35f;
	std::mt19937 rng( 3 );
	std::uniform_real_distribution<float> u( -110, 110 );
	for( int k = 0; k < 40; ++k )
	{
		const float x = u( rng ), z = u( rng );
		if( std::hypot( x, z ) < 26 || std::hypot( x - 40, z + 30 ) < 16 ) continue;
		b.foliage = k % 3 == 0 ? world::FoliageKind::Pine : world::FoliageKind::Tree;
		b.seed = uint32_t( k + 1 );
		t.Sculpt( x, z, b );
	}
	b.foliage = world::FoliageKind::Rock;
	b.density = 0.12f;
	for( int k = 0; k < 12; ++k ) { b.seed = uint32_t( 100 + k ); t.Sculpt( u( rng ), u( rng ), b ); }
	b.foliage = world::FoliageKind::Bush;
	b.density = 0.25f;
	for( int k = 0; k < 14; ++k ) { b.seed = uint32_t( 200 + k ); const float x = u( rng ) * 0.6f, z = u( rng ) * 0.6f; if( std::hypot( x, z ) > 16 ) t.Sculpt( x, z, b ); }

	auto ground = [&]( float x, float z ) { return Vector3( x, m_scene.GroundAt( x, z ), z ); };
	m_scene.Find( m_scene.FindByName( "PlayerStart1" )->id )->transform.position = ground( 0, 9 );
	// the camp: a group with a fire, tents and crates (a prefab-ready hierarchy)
	const uint32_t camp = m_scene.Create( ActorType::Empty, "Camp" ).id;
	m_scene.Find( camp )->transform.position = Vector3( 0, campY, 0 );
	auto child = [&]( ActorType type, const char* name, Vector3 at, const char* shape = nullptr, const char* color = nullptr, Vector3 scale = Vector3( 1, 1, 1 ) ) {
		world::Entity& e = m_scene.Create( type, name, camp );
		e.transform.position = at;
		e.transform.scale = scale;
		if( shape ) e.props["shape"] = shape;
		if( color ) e.props["color"] = color;
		return e.id;
	};
	child( ActorType::PointLight, "Campfire Light", Vector3( 0, 1.2f, 0 ) );
	child( ActorType::Mesh, "Campfire", Vector3( 0, 0, 0 ), "cone", "#c2552d", Vector3( 0.9f, 0.6f, 0.9f ) );
	child( ActorType::Mesh, "Tent", Vector3( -6, 0, -3 ), "cone", "#a8946b", Vector3( 4, 3, 4 ) );
	child( ActorType::Mesh, "Tent2", Vector3( 5, 0, -5 ), "cone", "#8c7a58", Vector3( 3.5f, 2.6f, 3.5f ) );
	child( ActorType::Mesh, "Crate", Vector3( 3, 0, 3 ), "cube", "#7a5a3a", Vector3( 1, 1, 1 ) );
	child( ActorType::Mesh, "Crate2", Vector3( 3.8f, 0, 4.1f ), "cube", "#6e5134", Vector3( 0.8f, 0.8f, 0.8f ) );
	const uint32_t giver = m_scene.Create( ActorType::QuestGiver, "Marshal Grey", camp ).id;
	m_scene.Find( giver )->transform.position = Vector3( -2.5f, 0, 2.5f );
	const uint32_t den = m_scene.Create( ActorType::CreatureSpawn, "Wolf Den" ).id;
	m_scene.Find( den )->transform.position = ground( 46, -34 );
	m_scene.Find( den )->props["count"] = 4;
	m_scene.Find( den )->props["wander"] = 9.0;
	const uint32_t boars = m_scene.Create( ActorType::CreatureSpawn, "Boar Field" ).id;
	m_scene.Find( boars )->transform.position = ground( -45, 35 );
	m_scene.Find( boars )->props["creature"] = "Boar";
	m_scene.Find( boars )->props["hostile"] = false;
	m_scene.Find( boars )->props["color"] = "#6b4a3a";
	const uint32_t zone = m_scene.Create( ActorType::Zone, "Vale Zone" ).id;
	m_scene.Find( zone )->transform.position = Vector3( 0, 15, 0 );
	m_scene.Find( zone )->props["size"] = { 250.0, 90.0, 250.0 };
	m_selected = 0;
	m_undo.clear();
	m_redo.clear();
	m_current = m_scene.ToJson().dump();
	m_pivot = Vector3( 0, campY, 0 );
	m_dist = 70;
	m_pitch = -0.42f;
	OrbitFromAngles();
	Print( "New Starter Zone: Greenhollow Vale - a camp with Marshal Grey (quest), wolves to the north-east, boars to the south-west. Alt+P to play." );
}

bool Editor::SaveLevel( const std::string& path )
{
	std::string err;
	std::error_code ec;
	if( fs::path( path ).has_parent_path() ) fs::create_directories( fs::path( path ).parent_path(), ec );
	if( !world::SaveLevel( m_scene, path, &err ) )
	{
		Print( "Save failed: " + err );
		return false;
	}
	levelPath = path;
	Print( "Saved " + path );
	return true;
}

bool Editor::OpenLevel( const std::string& path )
{
	Stop();
	world::Scene loaded;
	std::string err;
	if( !world::LoadLevel( loaded, path, &err ) )
	{
		Print( "Open failed: " + err );
		return false;
	}
	m_scene = std::move( loaded );
	m_selected = 0;
	m_undo.clear();
	m_redo.clear();
	m_current = m_scene.ToJson().dump();
	levelPath = path;
	Print( "Opened " + path + " (" + std::to_string( m_scene.Entities().size() ) + " actors)" );
	return true;
}

uint32_t Editor::Place( ActorType type, const Vector3& at, uint32_t parent )
{
	if( Playing() ) return 0;
	if( type == ActorType::Terrain ) return CreateTerrain( 256, 128, false );
	world::Entity& e = m_scene.Create( type, "", parent );
	e.transform.position = at;
	if( type == ActorType::PointLight ) e.transform.position.y += 2.5f;
	if( type == ActorType::DirLight ) { e.transform.position.y += 25; e.transform.rotation = Vector3( -48, 32, 0 ); }
	if( type == ActorType::TriggerBox ) e.transform.position.y += 1;
	if( type == ActorType::Zone ) e.transform.position.y += 10;
	const uint32_t id = e.id;
	m_selected = id;
	Commit( "Place" );
	Print( std::string( "Placed " ) + world::InfoOf( type ).label + " (" + m_scene.Find( id )->name + ")" );
	return id;
}

uint32_t Editor::PlaceModel( const std::string& rel, const Vector3& at )
{
	if( Playing() ) return 0;
	int tris = 0;
	std::string err;
	if( !m_renderer.ModelInfo( ( fs::path( m_settings.contentDir ) / rel ).string(), &tris, &err ) )
	{
		Print( "Model failed: " + err );
		return 0;
	}
	world::Entity& e = m_scene.Create( ActorType::Model, fs::path( rel ).stem().string() );
	e.transform.position = at;
	e.props["path"] = rel;
	const uint32_t id = e.id;
	m_selected = id;
	Commit( "Place model" );
	Print( "Placed model " + rel + " (" + std::to_string( tris ) + " triangles)" );
	return id;
}

world::json Editor::SubtreeJson( uint32_t root ) const
{
	world::json keep = world::json::array();
	if( !m_scene.Find( root ) ) return keep;
	const world::json all = m_scene.ToJson()["actors"];
	std::set<uint32_t> ids = { root };
	for( bool grew = true; grew; )
	{
		grew = false;
		for( const auto& e : m_scene.Entities() )
			if( !ids.count( e.id ) && ids.count( e.parent ) ) { ids.insert( e.id ); grew = true; }
	}
	for( auto a : all )
		if( ids.count( a["id"].get<uint32_t>() ) )
		{
			if( a["id"].get<uint32_t>() == root ) { a["parent"] = 0; a["position"] = { 0, 0, 0 }; }
			keep.push_back( a );
		}
	return keep;
}

bool Editor::SavePrefab( uint32_t root, const std::string& name )
{
	if( !m_scene.Find( root ) ) return false;
	const world::json keep = SubtreeJson( root );
	const fs::path path = fs::path( m_settings.contentDir ) / "prefabs" / ( name + ".prefab.json" );
	std::error_code ec;
	fs::create_directories( path.parent_path(), ec );
	std::ofstream f( path );
	f << world::json{ { "format", "cmmo-prefab" }, { "version", 1 }, { "actors", keep } }.dump( 1 );
	Print( "Saved prefab " + path.string() + " (" + std::to_string( keep.size() ) + " actors)" );
	return bool( f );
}

uint32_t Editor::PlaceActorsJson( const world::json& actors, const Vector3& at, const char* what )
{
	// rebuild through a temporary level so props / terrain load exactly like a level
	world::json level = { { "format", "cmmo-level" }, { "version", 2 }, { "actors", actors } };
	world::Scene tmp;
	std::string err;
	if( !tmp.FromJson( level, &err ) ) { Print( std::string( what ) + " failed: " + err ); return 0; }
	std::map<uint32_t, uint32_t> remap;
	uint32_t root = 0;
	for( const auto& e : tmp.Entities() )
	{
		world::Entity copy = e;
		if( copy.terrain ) copy.terrain = std::make_shared<world::Terrain>( *copy.terrain );
		copy.id = m_scene.nextId++;
		remap[e.id] = copy.id;
		if( !e.parent ) { root = copy.id; copy.transform.position = at; }
		if( m_scene.FindByName( copy.name ) ) copy.name = m_scene.UniqueName( copy.name );
		m_scene.Entities().push_back( copy );
	}
	for( const auto& e : tmp.Entities() )
		if( e.parent ) m_scene.Find( remap[e.id] )->parent = remap.count( e.parent ) ? remap[e.parent] : 0;
	m_selected = root;
	Commit( what );
	return root;
}

uint32_t Editor::PlacePrefab( const std::string& rel, const Vector3& at )
{
	if( Playing() ) return 0;
	const world::json doc = world::json::parse( ReadFile( fs::path( m_settings.contentDir ) / rel ), nullptr, false );
	if( doc.is_discarded() || doc.value( "format", "" ) != "cmmo-prefab" )
	{
		Print( "Not a prefab: " + rel );
		return 0;
	}
	const uint32_t root = PlaceActorsJson( doc["actors"], at, "Place prefab" );
	if( root ) Print( "Placed prefab " + rel );
	return root;
}

bool Editor::CopySelected()
{
	if( !m_scene.Find( m_selected ) ) return false;
	m_clipboard = SubtreeJson( m_selected );
	m_clipboardAt = m_scene.WorldPosition( m_selected );
	Print( "Copied " + m_scene.Find( m_selected )->name + ( m_clipboard.size() > 1 ? " (+" + std::to_string( m_clipboard.size() - 1 ) + " children)" : "" ) );
	return true;
}

uint32_t Editor::Paste()
{
	if( Playing() || m_clipboard.empty() ) return 0;
	m_clipboardAt += Vector3( 2, 0, 2 );   // each paste lands a little further on
	return PlaceActorsJson( m_clipboard, m_clipboardAt, "Paste" );
}

bool Editor::SnapSelectedToGround()
{
	world::Entity* e = m_scene.Find( m_selected );
	if( Playing() || !e || e->type == ActorType::Terrain ) return false;
	const Vector3 w = m_scene.WorldPosition( e->id );
	bool found = false;
	const float g = m_scene.GroundAt( w.x, w.z, &found );
	if( !found ) return false;
	e->transform.position.y += g - w.y;
	Commit( "Snap to ground" );
	return true;
}

uint32_t Editor::GroupSelected()
{
	world::Entity* e = m_scene.Find( m_selected );
	if( Playing() || !e ) return 0;
	const uint32_t child = e->id, oldParent = e->parent;
	const Vector3 at = m_scene.WorldPosition( child );
	world::Entity& g = m_scene.Create( ActorType::Empty, "Group", oldParent );
	g.transform.position = oldParent ? at - m_scene.WorldPosition( oldParent ) : at;
	const uint32_t gid = g.id;
	m_scene.SetParent( child, gid );
	m_selected = gid;
	Commit( "Group" );
	return gid;
}

bool Editor::DeleteSelected()
{
	if( Playing() || !m_scene.Find( m_selected ) ) return false;
	const std::string name = m_scene.Find( m_selected )->name;
	m_scene.Remove( m_selected );
	m_selected = 0;
	Commit( "Delete" );
	Print( "Deleted " + name );
	return true;
}

uint32_t Editor::DuplicateSelected()
{
	const world::Entity* src = m_scene.Find( m_selected );
	if( Playing() || !src || src->type == ActorType::Terrain ) return 0;
	// duplicate the whole subtree
	std::vector<uint32_t> order = { src->id };
	for( size_t k = 0; k < order.size(); ++k )
		for( uint32_t c : m_scene.Children( order[k] ) ) order.push_back( c );
	std::map<uint32_t, uint32_t> remap;
	std::vector<world::Entity> copies;
	for( uint32_t id : order )
	{
		world::Entity copy = *m_scene.Find( id );
		remap[id] = m_scene.nextId++;
		copy.id = remap[id];
		copies.push_back( copy );
	}
	for( auto& c : copies )
	{
		if( remap.count( c.parent ) ) c.parent = remap[c.parent];
		if( c.id == remap[order[0]] )
		{
			std::string stem = c.name;
			while( !stem.empty() && std::isdigit( (unsigned char)stem.back() ) ) stem.pop_back();
			c.name = m_scene.UniqueName( stem.empty() ? "Actor" : stem );
			c.transform.position += Vector3( 2, 0, 0 );
		}
		m_scene.Entities().push_back( c );
	}
	m_selected = remap[order[0]];
	Commit( "Duplicate" );
	return m_selected;
}

bool Editor::Reparent( uint32_t id, uint32_t parent )
{
	if( Playing() || !m_scene.SetParent( id, parent ) ) return false;
	Commit( "Reparent" );
	return true;
}

void Editor::Commit( const char* what )
{
	std::string now = m_scene.ToJson().dump();
	if( now == m_current ) return;
	m_undo.push_back( std::move( m_current ) );
	if( m_undo.size() > 60 ) m_undo.pop_front();
	m_redo.clear();
	m_current = std::move( now );
	(void)what;
}

bool Editor::Undo()
{
	if( Playing() || m_undo.empty() ) return false;
	m_redo.push_back( m_current );
	m_current = m_undo.back();
	m_undo.pop_back();
	m_scene.FromJson( world::json::parse( m_current ) );
	if( !m_scene.Find( m_selected ) ) m_selected = 0;
	return true;
}

bool Editor::Redo()
{
	if( Playing() || m_redo.empty() ) return false;
	m_undo.push_back( m_current );
	m_current = m_redo.back();
	m_redo.pop_back();
	m_scene.FromJson( world::json::parse( m_current ) );
	if( !m_scene.Find( m_selected ) ) m_selected = 0;
	return true;
}

bool Editor::Play( bool possess )
{
	if( Playing() ) return false;
	m_play = std::make_unique<world::PlaySession>( m_scene, possess );
	m_paused = false;
	m_stroke = false;
	Print( possess ? "Playing - W/S move, A/D turn, Q/E strafe, Space jump, Tab target, 1-4 abilities, F talk, right-drag turns, Esc stops."
				   : "Simulating - creatures run, the editor camera stays. Esc stops." );
	return true;
}

void Editor::Stop()
{
	if( !m_play ) return;
	char buf[96];
	std::snprintf( buf, sizeof( buf ), "Stopped after %.1f s - the level is exactly as it was.", m_play->Time() );
	Print( buf );
	m_play.reset();
	m_paused = false;
}

uint32_t Editor::CreateTerrain( float size, int res, bool generate )
{
	if( Playing() ) return 0;
	world::Entity& e = m_scene.Create( ActorType::Terrain );
	e.terrain = std::make_shared<world::Terrain>( res, size );
	if( generate ) e.terrain->Generate( uint32_t( m_genSeed ), m_genHeight, m_genFeature, m_genOctaves, false );
	const uint32_t id = e.id;
	m_selected = id;
	Commit( "Create terrain" );
	Print( "Created a " + std::to_string( int( size ) ) + " m terrain (" + std::to_string( res ) + " x " + std::to_string( res ) + ")" +
		   ( generate ? " from noise, seed " + std::to_string( m_genSeed ) : "" ) );
	return id;
}

void Editor::BeginStroke( const Vector3& p )
{
	m_stroke = true;
	m_brush.rampFrom = m_brush.rampTo = p;
	m_brush.rampFromH = m_brush.height = p.y;
	m_brush.seed = uint32_t( std::rand() ) + 1;
	StrokeTo( p );
}

bool Editor::StrokeTo( const Vector3& p )
{
	if( m_tool < 0 ) return false;
	m_brush.mode = world::Brush::Mode( m_tool );
	for( auto& e : m_scene.Entities() )
	{
		if( e.type != ActorType::Terrain || !e.terrain ) continue;
		const Vector3 o = m_scene.WorldPosition( e.id );
		const float lx = p.x - o.x, lz = p.z - o.z;
		if( !e.terrain->Inside( lx, lz ) ) continue;
		world::Brush b = m_brush;
		b.height -= o.y;
		b.rampFromH -= o.y;
		b.rampFrom = b.rampFrom - o;
		b.rampTo = p - o;
		b.rampToH = b.rampTo.y;
		if( b.mode == world::Brush::Ramp ) b.rampToH = e.terrain->HeightAt( lx, lz );
		return e.terrain->Sculpt( lx, lz, b ) > 0;
	}
	return false;
}

void Editor::EndStroke()
{
	if( !m_stroke ) return;
	m_stroke = false;
	Commit( "Terrain" );
}

void Editor::OrbitFromAngles()
{
	const float cp = std::cos( m_pitch );
	m_cam.target = m_pivot;
	m_cam.eye = m_pivot + Vector3( std::sin( m_yaw ) * cp, -std::sin( m_pitch ), std::cos( m_yaw ) * cp ) * m_dist;
}

void Editor::FrameSelected()
{
	const world::Entity* e = m_scene.Find( m_selected );
	if( !e ) return;
	m_pivot = m_scene.WorldPosition( e->id );
	if( e->terrain ) m_dist = e->terrain->Size() * 0.6f;
	else if( e->type == ActorType::Zone ) m_dist = 120;
	else m_dist = std::max( 7.0f, 4.0f * std::max( e->transform.scale.x, std::max( e->transform.scale.y, e->transform.scale.z ) ) );
	OrbitFromAngles();
}

Vector3 Editor::DropPoint( float mx, float my )
{
	Vector3 o, d, hit;
	m_cam.Ray( mx, my, m_viewW, m_viewH, o, d );
	if( m_scene.RaycastTerrain( o, d, hit ) ) return hit;
	if( d.y < -1e-3f ) return o + d * ( -o.y / d.y );
	return Vector3( m_pivot.x, 0, m_pivot.z );
}
Vector3 Editor::PlacementPoint() { return DropPoint( m_viewW * 0.5f, m_viewH * 0.5f ); }

// ------------------------------------------------------------------------------------------------ frame
void Editor::Frame( float dt )
{
	m_fps = m_fps * 0.95f + ( dt > 0 ? 1.0f / dt : 60.0f ) * 0.05f;
	ImGuizmo::BeginFrame();
	MenuBar();
	ImGuiViewport* vp = ImGui::GetMainViewport();
	const float tbH = ImGui::GetFrameHeight() + 18;
	ImGui::SetNextWindowPos( vp->WorkPos );
	ImGui::SetNextWindowSize( ImVec2( vp->WorkSize.x, tbH ) );
	ImGui::SetNextWindowViewport( vp->ID );
	ImGui::PushStyleVar( ImGuiStyleVar_WindowPadding, ImVec2( 0, 0 ) );
	ImGui::PushStyleVar( ImGuiStyleVar_WindowBorderSize, 0 );
	ImGui::PushStyleVar( ImGuiStyleVar_WindowRounding, 0 );
	ImGui::Begin( "##toolbar", nullptr, ImGuiWindowFlags_NoDecoration | ImGuiWindowFlags_NoDocking | ImGuiWindowFlags_NoMove | ImGuiWindowFlags_NoSavedSettings |
										 ImGuiWindowFlags_NoScrollbar | ImGuiWindowFlags_NoBringToFrontOnFocus );
	ImGui::PopStyleVar( 3 );
	Toolbar( tbH );
	ImGui::End();

	ImGui::SetNextWindowPos( ImVec2( vp->WorkPos.x, vp->WorkPos.y + tbH ) );
	ImGui::SetNextWindowSize( ImVec2( vp->WorkSize.x, vp->WorkSize.y - tbH ) );
	ImGui::SetNextWindowViewport( vp->ID );
	ImGui::PushStyleVar( ImGuiStyleVar_WindowPadding, ImVec2( 4, 4 ) );
	ImGui::PushStyleVar( ImGuiStyleVar_WindowBorderSize, 0 );
	ImGui::PushStyleVar( ImGuiStyleVar_WindowRounding, 0 );
	ImGui::Begin( "##dockhost", nullptr, ImGuiWindowFlags_NoDecoration | ImGuiWindowFlags_NoDocking | ImGuiWindowFlags_NoMove | ImGuiWindowFlags_NoSavedSettings |
										  ImGuiWindowFlags_NoBringToFrontOnFocus | ImGuiWindowFlags_NoNavFocus | ImGuiWindowFlags_NoBackground );
	ImGui::PopStyleVar( 3 );
	const ImGuiID dock = ImGui::GetID( "MainDock" );
	static bool laidOut = false;
	if( !laidOut || m_resetLayout )
	{
		laidOut = true;
		ImGuiDockNode* node = ImGui::DockBuilderGetNode( dock );
		if( m_resetLayout )
			for( bool& o : m_open ) o = true;
		if( m_resetLayout ) m_open[PControls] = m_open[PPrefs] = false;
		if( !node || node->IsLeafNode() || m_resetLayout )   // first run (or Window > Reset Layout): Unreal / Godot style
		{
			m_resetLayout = false;
			ImGui::DockBuilderRemoveNode( dock );
			ImGui::DockBuilderAddNode( dock, ImGuiDockNodeFlags_DockSpace );
			ImGui::DockBuilderSetNodeSize( dock, ImGui::GetContentRegionAvail() );
			ImGuiID center = dock;
			const ImGuiID left = ImGui::DockBuilderSplitNode( center, ImGuiDir_Left, 0.17f, nullptr, &center );
			const ImGuiID right = ImGui::DockBuilderSplitNode( center, ImGuiDir_Right, 0.24f, nullptr, &center );
			const ImGuiID bottom = ImGui::DockBuilderSplitNode( center, ImGuiDir_Down, 0.27f, nullptr, &center );
			ImGuiID leftBottom = 0, rightBottom = 0;
			const ImGuiID leftTop = ImGui::DockBuilderSplitNode( left, ImGuiDir_Up, 0.55f, nullptr, &leftBottom );
			const ImGuiID rightTop = ImGui::DockBuilderSplitNode( right, ImGuiDir_Up, 0.5f, nullptr, &rightBottom );
			ImGui::DockBuilderDockWindow( ICON_FA_CUBES " Viewport", center );
			ImGui::DockBuilderDockWindow( ICON_FA_SITEMAP " Scene", leftTop );
			ImGui::DockBuilderDockWindow( ICON_FA_PLUS " Place Actors", leftBottom );
			ImGui::DockBuilderDockWindow( ICON_FA_SLIDERS " Inspector", rightTop );
			ImGui::DockBuilderDockWindow( ICON_FA_GLOBE " World Settings", rightBottom );
			ImGui::DockBuilderDockWindow( ICON_FA_MOUNTAIN_SUN " Terrain", rightBottom );
			ImGui::DockBuilderDockWindow( ICON_FA_FOLDER_OPEN " Content Browser", bottom );
			ImGui::DockBuilderDockWindow( ICON_FA_TERMINAL " Output", bottom );
			ImGui::DockBuilderFinish( dock );
		}
	}
	ImGui::DockSpace( dock, ImVec2( 0, 0 ), ImGuiDockNodeFlags_None );
	ImGui::End();

	Hotkeys();
	ViewportPanel( dt );
	ScenePanel();
	PlacePanel();
	InspectorPanel();
	WorldPanel();
	TerrainPanel();
	OutputPanel();
	ContentPanel();
	ControlsPanel();
	PrefsPanel();
	if( m_showDemo ) ImGui::ShowDemoWindow( &m_showDemo );
	if( m_play )
		for( auto& line : m_play->TakeLog() ) Print( line );
}

void Editor::PlaceMenuItems( const Vector3& at )
{
	for( const char* group : { "Gameplay", "World", "Basic", "Lighting" } )
	{
		ImGui::SeparatorText( group );
		for( const auto& a : world::Actors() )
			if( std::string( a.group ) == group && ImGui::MenuItem( ( std::string( IconOf( a.type ) ) + "  " + a.label ).c_str() ) ) Place( a.type, at );
	}
}

void Editor::MenuBar()
{
	if( !ImGui::BeginMainMenuBar() ) return;
	const bool edit = !Playing(), sel = edit && m_scene.Find( m_selected );
	const std::string saveTo = levelPath.empty() ? ( fs::path( m_settings.contentDir ) / "levels" / ( std::string( m_saveName ) + ".level.json" ) ).string() : levelPath;
	ImGui::PushStyleColor( ImGuiCol_Text, IM_COL32( 120, 175, 240, 255 ) );
	ImGui::TextUnformatted( ICON_FA_GEM );
	ImGui::PopStyleColor();
	if( ImGui::BeginMenu( "File" ) )
	{
		ImGui::SeparatorText( "Level" );
		if( ImGui::MenuItem( ICON_FA_FILE "  New Level", nullptr, false, edit ) ) NewLevel();
		if( ImGui::MenuItem( ICON_FA_MOUNTAIN_SUN "  New Starter Zone", nullptr, false, edit ) ) NewStarterZone();
		if( ImGui::BeginMenu( ICON_FA_FOLDER_OPEN "  Open Level", edit ) )
		{
			std::error_code ec;
			int n = 0;
			for( const auto& f : fs::directory_iterator( fs::path( m_settings.contentDir ) / "levels", ec ) )
				if( EndsWith( f.path().filename().string(), ".level.json" ) && ImGui::MenuItem( f.path().filename().string().c_str() ) ) { OpenLevel( f.path().string() ); ++n; }
				else if( EndsWith( f.path().filename().string(), ".level.json" ) ) ++n;
			if( !n ) ImGui::TextDisabled( "No levels saved yet" );
			ImGui::EndMenu();
		}
		ImGui::Separator();
		if( ImGui::MenuItem( ICON_FA_FLOPPY_DISK "  Save Level", "Ctrl+S" ) ) SaveLevel( saveTo );
		if( ImGui::MenuItem( ICON_FA_PEN_TO_SQUARE "  Save Level As..." ) ) { m_open[PContent] = true; m_contentTab = 0; ImGui::SetWindowFocus( ICON_FA_FOLDER_OPEN " Content Browser" ); }
		ImGui::Separator();
		if( ImGui::MenuItem( ICON_FA_RIGHT_FROM_BRACKET "  Quit" ) ) m_quit = true;
		ImGui::EndMenu();
	}
	if( ImGui::BeginMenu( "Edit" ) )
	{
		if( ImGui::MenuItem( ICON_FA_ROTATE_LEFT "  Undo", "Ctrl+Z", false, edit && !m_undo.empty() ) ) Undo();
		if( ImGui::MenuItem( ICON_FA_ROTATE_RIGHT "  Redo", "Ctrl+Shift+Z", false, edit && !m_redo.empty() ) ) Redo();
		ImGui::Separator();
		if( ImGui::MenuItem( ICON_FA_SCISSORS "  Cut", "Ctrl+X", false, sel ) && CopySelected() ) DeleteSelected();
		if( ImGui::MenuItem( ICON_FA_COPY "  Copy", "Ctrl+C", false, sel ) ) CopySelected();
		if( ImGui::MenuItem( ICON_FA_PASTE "  Paste", "Ctrl+V", false, edit && !m_clipboard.empty() ) ) Paste();
		if( ImGui::MenuItem( ICON_FA_CLONE "  Duplicate", "Ctrl+D", false, sel ) ) DuplicateSelected();
		if( ImGui::MenuItem( ICON_FA_TRASH "  Delete", "Del", false, sel ) ) DeleteSelected();
		ImGui::Separator();
		if( ImGui::MenuItem( ICON_FA_XMARK "  Select None", nullptr, false, m_selected != 0 ) ) m_selected = 0;
		ImGui::Separator();
		if( ImGui::MenuItem( ICON_FA_GEAR "  Editor Preferences..." ) ) m_open[PPrefs] = true;
		ImGui::EndMenu();
	}
	if( ImGui::BeginMenu( "Actor" ) )
	{
		if( ImGui::BeginMenu( ICON_FA_PLUS "  Place Actor", edit ) )
		{
			PlaceMenuItems( PlacementPoint() );
			ImGui::EndMenu();
		}
		ImGui::Separator();
		if( ImGui::MenuItem( ICON_FA_OBJECT_GROUP "  Group", "Ctrl+G", false, sel ) ) GroupSelected();
		if( ImGui::MenuItem( ICON_FA_ARROW_UP "  Unparent", nullptr, false, sel && m_scene.Find( m_selected )->parent ) ) Reparent( m_selected, 0 );
		if( ImGui::MenuItem( ICON_FA_ARROW_DOWN "  Snap to Ground", "End", false, sel ) ) SnapSelectedToGround();
		if( ImGui::MenuItem( ICON_FA_EYE_SLASH "  Hide / Show", "H", false, sel ) ) { m_scene.Find( m_selected )->visible = !m_scene.Find( m_selected )->visible; Commit( "Visibility" ); }
		if( ImGui::MenuItem( ICON_FA_PEN "  Rename", "F2", false, sel ) ) { m_renaming = m_selected; std::snprintf( m_renameBuf, sizeof( m_renameBuf ), "%s", m_scene.Find( m_selected )->name.c_str() ); m_open[PScene] = true; }
		if( ImGui::MenuItem( ICON_FA_BOX "  Save as Prefab", nullptr, false, sel ) ) SavePrefab( m_selected, m_scene.Find( m_selected )->name );
		ImGui::Separator();
		if( ImGui::MenuItem( ICON_FA_CROSSHAIRS "  Focus", "F", false, m_selected != 0 ) ) FrameSelected();
		ImGui::EndMenu();
	}
	if( ImGui::BeginMenu( "Terrain" ) )
	{
		world::Terrain* t = m_scene.FirstTerrain();
		if( !t )
		{
			if( ImGui::MenuItem( ICON_FA_SQUARE "  Create Flat Terrain", nullptr, false, edit ) ) CreateTerrain( 256, 128, false );
			if( ImGui::MenuItem( ICON_FA_DICE "  Create from Noise", nullptr, false, edit ) ) CreateTerrain( 256, 128, true );
		}
		else
		{
			ImGui::SeparatorText( "Sculpt & Paint" );
			for( const auto& tool : kTools )
				if( ImGui::MenuItem( ( std::string( tool.icon ) + "  " + tool.name ).c_str(), nullptr, m_tool == int( tool.mode ), edit ) )
				{
					m_tool = m_tool == int( tool.mode ) ? -1 : int( tool.mode );
					m_open[PTerrain] = true;
				}
			if( ImGui::MenuItem( ICON_FA_ARROW_POINTER "  Stop Terrain Tool", "Esc", false, m_tool >= 0 ) ) m_tool = -1;
			ImGui::Separator();
			if( ImGui::MenuItem( ICON_FA_ARROWS_ROTATE "  Regenerate Heights", nullptr, false, edit ) ) { t->Generate( uint32_t( m_genSeed ), m_genHeight, m_genFeature, m_genOctaves, false ); Commit( "Generate" ); }
			if( ImGui::MenuItem( ICON_FA_BROOM "  Clear Foliage", nullptr, false, edit ) ) { t->ClearFoliage(); Commit( "Clear foliage" ); }
		}
		ImGui::Separator();
		if( ImGui::MenuItem( ICON_FA_SLIDERS "  Terrain Panel" ) ) { m_open[PTerrain] = true; ImGui::SetWindowFocus( ICON_FA_MOUNTAIN_SUN " Terrain" ); }
		ImGui::EndMenu();
	}
	if( ImGui::BeginMenu( "Play" ) )
	{
		if( ImGui::MenuItem( ICON_FA_PLAY "  Play in Editor", "Alt+P", false, !Playing() ) ) Play( true );
		if( ImGui::MenuItem( ICON_FA_FILM "  Simulate", nullptr, false, !Playing() ) ) Play( false );
		if( ImGui::MenuItem( ICON_FA_PAUSE "  Pause", nullptr, m_paused, Playing() ) ) m_paused = !m_paused;
		if( ImGui::MenuItem( ICON_FA_STOP "  Stop", "Esc", false, Playing() ) ) Stop();
		ImGui::EndMenu();
	}
	if( ImGui::BeginMenu( "View" ) )
	{
		ImGui::SeparatorText( "Viewport" );
		if( ImGui::MenuItem( ICON_FA_SUN "  Lit", nullptr, m_viewMode == ViewMode::Lit ) ) m_viewMode = ViewMode::Lit;
		if( ImGui::MenuItem( ICON_FA_CIRCLE_HALF_STROKE "  Unlit", nullptr, m_viewMode == ViewMode::Unlit ) ) m_viewMode = ViewMode::Unlit;
		if( ImGui::MenuItem( ICON_FA_DRAW_POLYGON "  Wireframe", nullptr, m_viewMode == ViewMode::Wireframe ) ) m_viewMode = ViewMode::Wireframe;
		ImGui::Separator();
		ImGui::MenuItem( ICON_FA_TABLE_CELLS "  Grid", nullptr, &m_grid );
		ImGui::MenuItem( ICON_FA_CHART_LINE "  Stats", nullptr, &m_stats );
		if( ImGui::BeginMenu( ICON_FA_GAUGE_HIGH "  Camera Speed" ) )
		{
			for( int k = 1; k <= 8; ++k )
			{
				char b[32];
				std::snprintf( b, sizeof( b ), "Speed %d", k );
				if( ImGui::MenuItem( b, nullptr, m_camSpeed == k ) ) m_camSpeed = k;
			}
			ImGui::EndMenu();
		}
		if( ImGui::MenuItem( ICON_FA_CROSSHAIRS "  Frame Selected", "F", false, m_selected != 0 ) ) FrameSelected();
		ImGui::EndMenu();
	}
	if( ImGui::BeginMenu( "Window" ) )
	{
		ImGui::MenuItem( ICON_FA_SITEMAP "  Scene", nullptr, &m_open[PScene] );
		ImGui::MenuItem( ICON_FA_SLIDERS "  Inspector", nullptr, &m_open[PInspector] );
		ImGui::MenuItem( ICON_FA_PLUS "  Place Actors", nullptr, &m_open[PPlace] );
		ImGui::MenuItem( ICON_FA_MOUNTAIN_SUN "  Terrain", nullptr, &m_open[PTerrain] );
		ImGui::MenuItem( ICON_FA_GLOBE "  World Settings", nullptr, &m_open[PWorld] );
		ImGui::MenuItem( ICON_FA_FOLDER_OPEN "  Content Browser", nullptr, &m_open[PContent] );
		ImGui::MenuItem( ICON_FA_TERMINAL "  Output", nullptr, &m_open[POutput] );
		ImGui::Separator();
		if( ImGui::MenuItem( ICON_FA_TABLE_COLUMNS "  Reset Layout" ) ) m_resetLayout = true;
		ImGui::MenuItem( "ImGui widget demo", nullptr, &m_showDemo );
		ImGui::EndMenu();
	}
	if( ImGui::BeginMenu( "Help" ) )
	{
		if( ImGui::MenuItem( ICON_FA_KEYBOARD "  Controls", "F1" ) ) m_open[PControls] = true;
		ImGui::Separator();
		ImGui::TextDisabled( "Carbon Editor - Carbon math, Dear ImGui, AGPL LOKI" );
		ImGui::EndMenu();
	}
	const std::string world = m_scene.settings.value( "name", std::string( "New World" ) ) + ( levelPath.empty() ? "  (unsaved)" : "  -  " + fs::path( levelPath ).filename().string() );
	ImGui::SameLine( ImGui::GetWindowWidth() - ImGui::CalcTextSize( world.c_str() ).x - 16 );
	ImGui::TextDisabled( "%s", world.c_str() );
	ImGui::EndMainMenuBar();
}

void Editor::Toolbar( float height )
{
	ui::ToolbarBackground( height );
	ImGui::SetCursorPos( ImVec2( 10, 7 ) );
	const std::string save = levelPath.empty() ? ( fs::path( m_settings.contentDir ) / "levels" / ( std::string( m_saveName ) + ".level.json" ) ).string() : levelPath;
	if( ui::ToolButton( ICON_FA_FLOPPY_DISK, "Save Level", "Ctrl+S - saves to the Content Browser's levels." ) ) SaveLevel( save );
	ImGui::SameLine( 0, 4 );
	ImGui::BeginDisabled( m_undo.empty() || Playing() );
	if( ui::ToolButton( ICON_FA_ROTATE_LEFT, "Undo", "Ctrl+Z" ) ) Undo();
	ImGui::EndDisabled();
	ImGui::SameLine( 0, 4 );
	ImGui::BeginDisabled( m_redo.empty() || Playing() );
	if( ui::ToolButton( ICON_FA_ROTATE_RIGHT, "Redo", "Ctrl+Shift+Z" ) ) Redo();
	ImGui::EndDisabled();
	ImGui::SameLine( 0, 16 );
	struct Op { const char* icon; const char* name; const char* what; };
	const Op ops[] = { { ICON_FA_ARROW_POINTER, "Select (Q)", "Click actors in the viewport." },
					   { ICON_FA_ARROWS_UP_DOWN_LEFT_RIGHT, "Move (W)", "Drag the arrows or planes." },
					   { ICON_FA_ROTATE, "Rotate (E)", "Drag the rings." },
					   { ICON_FA_EXPAND, "Scale (R)", "Drag the handles." } };
	for( int i = 0; i < 4; ++i )
	{
		if( i ) ImGui::SameLine( 0, 4 );
		if( ui::ToolButton( ops[i].icon, ops[i].name, ops[i].what, m_gizmoOp == i ) ) m_gizmoOp = i;
	}
	ImGui::SameLine( 0, 4 );
	if( ui::ToolButton( m_local ? ICON_FA_CUBE : ICON_FA_GLOBE, m_local ? "Local space" : "World space", "Which axes the handles use." ) ) m_local = !m_local;
	ImGui::SameLine( 0, 4 );
	if( ui::ToolButton( ICON_FA_SQUARE_PLUS, "Quick Add", "Add an actor where the viewport looks (like Unreal's Quick Add).", false, 0, ui::col::Gold ) ) ImGui::OpenPopup( "##quickadd" );
	if( ImGui::BeginPopup( "##quickadd" ) )
	{
		PlaceMenuItems( PlacementPoint() );
		ImGui::EndPopup();
	}
	ImGui::SameLine( 0, 4 );
	if( ui::ToolButton( ICON_FA_MAGNET, "Snap", "Snap moves to the grid, rotations to 15 degrees, scales to 0.25.", m_snap ) ) m_snap = !m_snap;
	if( m_snap )
	{
		ImGui::SameLine( 0, 4 );
		ImGui::SetNextItemWidth( 64 );
		ImGui::SetCursorPosY( ImGui::GetCursorPosY() + 2 );
		ImGui::DragFloat( "##snap", &m_snapMove, 0.05f, 0.1f, 50.0f, "%.2f m" );
	}

	// play controls in the middle
	const float bw = ImGui::GetFrameHeight() + 6, groupW = bw * 4 + 12;
	ImGui::SameLine( ( ImGui::GetWindowWidth() - groupW ) * 0.5f );
	ImGui::SetCursorPosY( 7 );
	if( !Playing() )
	{
		if( ui::ToolButton( ICON_FA_PLAY, "Play", "Alt+P - play from the Player Start (third person, WoW controls).", false, 0, ui::col::Play ) ) Play( true );
		ImGui::SameLine( 0, 4 );
		if( ui::ToolButton( ICON_FA_FILM, "Simulate", "Run the world (creatures, scripts) with the editor camera." ) ) Play( false );
	}
	else
	{
		if( ui::ToolButton( m_paused ? ICON_FA_PLAY : ICON_FA_PAUSE, m_paused ? "Resume" : "Pause", "Freeze the world.", m_paused ) ) m_paused = !m_paused;
		ImGui::SameLine( 0, 4 );
		if( ui::ToolButton( ICON_FA_STOP, "Stop", "Esc - back to editing; the level is exactly as it was.", true, 0, ui::col::Stop ) ) Stop();
	}
	ImGui::SameLine( 0, 10 );
	ImGui::SetCursorPosY( 7 + 5 );
	if( Playing() ) ImGui::TextColored( ImVec4( 0.35f, 0.9f, 0.55f, 1 ), ICON_FA_CIRCLE " %s  %.1f s", m_paused ? "PAUSED" : "PLAYING", m_play->Time() );
	else ImGui::TextDisabled( "Ready" );

	// right side: view
	const float rightW = 3 * ( bw + 4 ) + 120;
	ImGui::SameLine( ImGui::GetWindowWidth() - rightW );
	ImGui::SetCursorPosY( 7 );
	const char* modes[] = { ICON_FA_SUN " Lit", ICON_FA_CIRCLE_HALF_STROKE " Unlit", ICON_FA_DRAW_POLYGON " Wireframe" };
	ImGui::SetNextItemWidth( 120 );
	ImGui::SetCursorPosY( 9 );
	int mode = int( m_viewMode );
	if( ImGui::Combo( "##mode", &mode, modes, 3 ) ) m_viewMode = ViewMode( mode );
	ui::Tip( "View mode", "Lit, Unlit (flat colours), or Wireframe." );
	ImGui::SameLine( 0, 4 );
	ImGui::SetCursorPosY( 7 );
	if( ui::ToolButton( ICON_FA_TABLE_CELLS, "Grid", "Show the ground grid.", m_grid ) ) m_grid = !m_grid;
	ImGui::SameLine( 0, 4 );
	if( ui::ToolButton( ICON_FA_CHART_LINE, "Stats", "Frame rate, draw calls, triangles, actors.", m_stats ) ) m_stats = !m_stats;
	ImGui::SameLine( 0, 4 );
	if( ui::ToolButton( ICON_FA_CROSSHAIRS, "Frame Selected", "F - centre the camera on the selection." ) ) FrameSelected();
}

void Editor::Hotkeys()
{
	ImGuiIO& io = ImGui::GetIO();
	if( Playing() )
	{
		if( ImGui::IsKeyPressed( ImGuiKey_Escape, false ) )
		{
			if( m_play->talkingTo >= 0 ) m_play->talkingTo = -1;
			else Stop();
		}
		return;
	}
	if( ImGui::IsKeyPressed( ImGuiKey_P, false ) && io.KeyAlt ) { Play( true ); return; }
	if( ImGui::Shortcut( ImGuiMod_Ctrl | ImGuiKey_Z, ImGuiInputFlags_RouteGlobal ) ) Undo();
	if( ImGui::Shortcut( ImGuiMod_Ctrl | ImGuiMod_Shift | ImGuiKey_Z, ImGuiInputFlags_RouteGlobal ) || ImGui::Shortcut( ImGuiMod_Ctrl | ImGuiKey_Y, ImGuiInputFlags_RouteGlobal ) ) Redo();
	if( ImGui::Shortcut( ImGuiMod_Ctrl | ImGuiKey_S, ImGuiInputFlags_RouteGlobal ) )
		SaveLevel( levelPath.empty() ? ( fs::path( m_settings.contentDir ) / "levels" / ( std::string( m_saveName ) + ".level.json" ) ).string() : levelPath );
	if( ImGui::Shortcut( ImGuiMod_Ctrl | ImGuiKey_D, ImGuiInputFlags_RouteGlobal ) ) DuplicateSelected();
	if( ImGui::IsKeyPressed( ImGuiKey_F1, false ) ) m_open[PControls] = !m_open[PControls];
	if( io.WantTextInput ) return;
	// these would also copy text in a field, so only outside text fields
	if( ImGui::Shortcut( ImGuiMod_Ctrl | ImGuiKey_C, ImGuiInputFlags_RouteGlobal ) ) CopySelected();
	if( ImGui::Shortcut( ImGuiMod_Ctrl | ImGuiKey_X, ImGuiInputFlags_RouteGlobal ) && CopySelected() ) DeleteSelected();
	if( ImGui::Shortcut( ImGuiMod_Ctrl | ImGuiKey_V, ImGuiInputFlags_RouteGlobal ) ) Paste();
	if( ImGui::Shortcut( ImGuiMod_Ctrl | ImGuiKey_G, ImGuiInputFlags_RouteGlobal ) ) GroupSelected();
	if( ImGui::IsKeyPressed( ImGuiKey_Delete, false ) || ( ImGui::IsKeyPressed( ImGuiKey_Backspace, false ) && io.KeySuper ) ) DeleteSelected();
	if( ImGui::IsKeyPressed( ImGuiKey_Escape, false ) ) m_tool = -1;
	// while the right mouse button flies the camera, W A S D Q E move it - they are not tool keys then (Unreal)
	if( m_flying ) return;
	if( !io.KeyCtrl && !io.KeyAlt && !io.KeySuper )
	{
		if( ImGui::IsKeyPressed( ImGuiKey_End, false ) ) SnapSelectedToGround();
		if( ImGui::IsKeyPressed( ImGuiKey_H, false ) && m_scene.Find( m_selected ) ) { m_scene.Find( m_selected )->visible = !m_scene.Find( m_selected )->visible; Commit( "Visibility" ); }
		if( ImGui::IsKeyPressed( ImGuiKey_Q, false ) ) { m_gizmoOp = 0; m_tool = -1; }
		if( ImGui::IsKeyPressed( ImGuiKey_W, false ) ) { m_gizmoOp = 1; m_tool = -1; }
		if( ImGui::IsKeyPressed( ImGuiKey_E, false ) ) { m_gizmoOp = 2; m_tool = -1; }
		if( ImGui::IsKeyPressed( ImGuiKey_R, false ) ) { m_gizmoOp = 3; m_tool = -1; }
		if( ImGui::IsKeyPressed( ImGuiKey_F, false ) ) FrameSelected();
		if( ImGui::IsKeyPressed( ImGuiKey_F2, false ) && m_selected ) { m_renaming = m_selected; std::snprintf( m_renameBuf, sizeof( m_renameBuf ), "%s", m_scene.Find( m_selected )->name.c_str() ); }
	}
}

// ------------------------------------------------------------------------------------------------ viewport
void Editor::ViewportPanel( float dt )
{
	ImGui::PushStyleVar( ImGuiStyleVar_WindowPadding, ImVec2( 0, 0 ) );
	ImGui::Begin( ICON_FA_CUBES " Viewport", nullptr, ImGuiWindowFlags_NoScrollbar | ImGuiWindowFlags_NoScrollWithMouse );
	ImGui::PopStyleVar();
	const ImVec2 avail = ImGui::GetContentRegionAvail();
	const ImVec2 origin = ImGui::GetCursorScreenPos();
	m_viewX = origin.x;
	m_viewY = origin.y;
	m_viewW = std::max( 16.0f, avail.x );
	m_viewH = std::max( 16.0f, avail.y );
	const float fb = ImGui::GetIO().DisplayFramebufferScale.x > 0 ? ImGui::GetIO().DisplayFramebufferScale.x : 1.0f;

	ImGui::SetNextItemAllowOverlap();
	ImGui::InvisibleButton( "##viewport", ImVec2( m_viewW, m_viewH ), ImGuiButtonFlags_MouseButtonLeft | ImGuiButtonFlags_MouseButtonRight | ImGuiButtonFlags_MouseButtonMiddle );
	const bool hovered = ImGui::IsItemHovered( ImGuiHoveredFlags_AllowWhenOverlappedByItem );
	if( ImGui::IsItemActivated() ) ImGui::SetWindowFocus();
	// drop targets: actors from Place Actors, models / prefabs / levels from the Content Browser
	if( ImGui::BeginDragDropTarget() )
	{
		const ImVec2 m = ImGui::GetMousePos();
		if( const ImGuiPayload* p = ImGui::AcceptDragDropPayload( "CMMO_ACTOR" ) ) Place( ActorType( *(const int*)p->Data ), DropPoint( m.x - origin.x, m.y - origin.y ) );
		if( const ImGuiPayload* p = ImGui::AcceptDragDropPayload( "CMMO_ASSET" ) )
		{
			const std::string rel( (const char*)p->Data );
			if( EndsWith( rel, ".prefab.json" ) ) PlacePrefab( rel, DropPoint( m.x - origin.x, m.y - origin.y ) );
			else if( EndsWith( rel, ".level.json" ) ) OpenLevel( ( fs::path( m_settings.contentDir ) / rel ).string() );
			else PlaceModel( rel, DropPoint( m.x - origin.x, m.y - origin.y ) );
		}
		ImGui::EndDragDropTarget();
	}

	if( Playing() )
	{
		GatherPlayInput( hovered, origin.x, origin.y );
		if( m_play->Possessed() ) m_play->CameraEyeTarget( m_cam.eye, m_cam.target );
	}
	else
		Navigation( hovered, origin.x, origin.y );

	FrameInfo info;
	info.scene = &m_scene;
	info.play = m_play.get();
	info.camera = m_cam;
	info.selected = m_selected;
	info.grid = m_grid;
	info.mode = m_viewMode;
	info.brushVisible = m_tool >= 0 && m_brushHover;
	info.brushPos = m_brushPos;
	info.brushRadius = m_brush.radius;
	info.contentDir = m_settings.contentDir;
	m_renderer.Render( int( m_viewW * fb ), int( m_viewH * fb ), info );

	ImDrawList* dl = ImGui::GetWindowDrawList();
	dl->AddImage( ImTextureRef( (ImTextureID)(intptr_t)m_renderer.ColorTexture() ), origin, ImVec2( origin.x + m_viewW, origin.y + m_viewH ), ImVec2( 0, 1 ), ImVec2( 1, 0 ) );

	// move / rotate / scale handles (ImGuizmo composes S * Rx * Ry * Rz * T, like world::Transform)
	world::Entity* sel = m_scene.Find( m_selected );
	static bool wasUsing = false;
	m_gizmoHover = false;
	if( sel && !Playing() && m_gizmoOp > 0 && m_tool < 0 )
	{
		ImGuizmo::SetOrthographic( false );
		ImGuizmo::SetDrawlist( dl );
		ImGuizmo::SetRect( origin.x, origin.y, m_viewW, m_viewH );
		const Matrix view = m_cam.View(), proj = m_cam.Projection( m_viewW / m_viewH );
		Matrix world = m_scene.WorldMatrix( sel->id );
		const ImGuizmo::OPERATION op = m_gizmoOp == 1 || sel->type == ActorType::Terrain ? ImGuizmo::TRANSLATE : m_gizmoOp == 2 ? ImGuizmo::ROTATE : ImGuizmo::SCALE;
		const float snapMove[3] = { m_snapMove, m_snapMove, m_snapMove }, snapRot[3] = { 15, 15, 15 }, snapScale[3] = { 0.25f, 0.25f, 0.25f };
		const float* snap = !m_snap ? nullptr : op == ImGuizmo::TRANSLATE ? snapMove : op == ImGuizmo::ROTATE ? snapRot : snapScale;
		if( ImGuizmo::Manipulate( &view._11, &proj._11, op, m_local ? ImGuizmo::LOCAL : ImGuizmo::WORLD, &world._11, nullptr, snap ) )
		{
			const Matrix local = sel->parent ? world * Inverse( m_scene.WorldMatrix( sel->parent ) ) : world;
			Vector3& p = sel->transform.position;
			Vector3& r = sel->transform.rotation;
			Vector3& s = sel->transform.scale;
			ImGuizmo::DecomposeMatrixToComponents( &local._11, &p.x, &r.x, &s.x );
		}
		const bool using_ = ImGuizmo::IsUsing();
		if( wasUsing && !using_ ) Commit( "Transform" );
		wasUsing = using_;
		m_gizmoHover = ImGuizmo::IsOver() || using_;
	}
	else
		wasUsing = false;

	if( Playing() ) Hud( origin.x, origin.y );
	else
	{
		ViewportOverlay( origin.x, origin.y );
		ViewportContextMenu();
	}
	if( Playing() ) dl->AddRect( origin, ImVec2( origin.x + m_viewW, origin.y + m_viewH ), m_paused ? IM_COL32( 240, 196, 70, 255 ) : IM_COL32( 61, 200, 120, 255 ), 0.0f, 0, 2.0f );
	(void)dt;
	ImGui::End();
}

void Editor::ViewportOverlay( float ox, float oy )
{
	ImDrawList* dl = ImGui::GetWindowDrawList();
	// view cube (top right): click a face to look along it, drag to orbit
	const float cube = 110;
	Matrix view = m_cam.View();
	const Matrix before = view;
	ImGuizmo::ViewManipulate( &view._11, m_dist, ImVec2( ox + m_viewW - cube - 10, oy + 10 ), ImVec2( cube, cube ), IM_COL32( 0, 0, 0, 0 ) );
	if( std::memcmp( &view, &before, sizeof( Matrix ) ) != 0 )
	{
		const Matrix inv = Inverse( view );
		const Vector3 eye( inv._41, inv._42, inv._43 ), z = Normalize( Vector3( inv._31, inv._32, inv._33 ) );
		m_pivot = eye - z * m_dist;
		m_yaw = std::atan2( z.x, z.z );
		m_pitch = -std::asin( std::max( -1.0f, std::min( 1.0f, z.y ) ) );
		OrbitFromAngles();
	}
	// camera speed (top right, left of the view cube) - like Unreal's viewport camera-speed button
	{
		char label[48];
		std::snprintf( label, sizeof( label ), ICON_FA_VIDEO "  %d", m_camSpeed );
		const ImVec2 ls = ImGui::CalcTextSize( label );
		ImGui::SetCursorScreenPos( ImVec2( ox + m_viewW - cube - 30 - ls.x - 16, oy + 12 ) );
		ImGui::PushStyleColor( ImGuiCol_Button, IM_COL32( 14, 15, 17, 170 ) );
		if( ImGui::Button( label ) ) ImGui::OpenPopup( "##camspeed" );
		ImGui::PopStyleColor();
		ui::Tip( "Camera speed", "How fast W A S D fly while you hold the right mouse button. The mouse wheel changes it while flying." );
		if( ImGui::BeginPopup( "##camspeed" ) )
		{
			ImGui::SetNextItemWidth( 160 );
			ImGui::SliderInt( "Speed", &m_camSpeed, 1, 8 );
			ImGui::TextDisabled( "%.1f m/s (Shift: x3)", CameraSpeedMps() );
			ImGui::SetNextItemWidth( 160 );
			ImGui::SliderFloat( "Mouse look", &m_lookSens, 0.25f, 3.0f, "%.2f" );
			ImGui::EndPopup();
		}
	}
	if( m_flying )
	{
		const char* fly = ICON_FA_PLANE "  Flying - W A S D move, Q / E down / up, wheel = speed, Shift = fast";
		const ImVec2 fs = ImGui::CalcTextSize( fly );
		const ImVec2 a( ox + ( m_viewW - fs.x ) * 0.5f, oy + m_viewH - fs.y - 26 );
		dl->AddRectFilled( ImVec2( a.x - 12, a.y - 6 ), ImVec2( a.x + fs.x + 12, a.y + fs.y + 6 ), IM_COL32( 14, 15, 17, 190 ), 6 );
		dl->AddText( a, IM_COL32( 220, 225, 232, 255 ), fly );
	}
	// stats (bottom left)
	if( m_stats )
	{
		const FrameStats& s = m_renderer.Stats();
		char buf[256];
		std::snprintf( buf, sizeof( buf ), "%.0f fps  %.1f ms\n%d draws  %d tris\n%d actors  %d foliage", m_fps, 1000.0f / std::max( 1.0f, m_fps ), s.drawCalls, s.triangles,
					   int( m_scene.Entities().size() ), s.foliage );
		const ImVec2 ts = ImGui::CalcTextSize( buf );
		const ImVec2 a( ox + 10, oy + m_viewH - ts.y - 22 );
		dl->AddRectFilled( a, ImVec2( a.x + ts.x + 16, a.y + ts.y + 12 ), IM_COL32( 14, 15, 17, 170 ), 6 );
		dl->AddText( ImVec2( a.x + 8, a.y + 6 ), IM_COL32( 205, 215, 225, 255 ), buf );
	}
	// tool chip (top left)
	std::string chip = m_viewMode == ViewMode::Lit ? ICON_FA_VIDEO " Perspective  " ICON_FA_SUN " Lit" : m_viewMode == ViewMode::Unlit ? ICON_FA_VIDEO " Perspective  Unlit" : ICON_FA_VIDEO " Perspective  Wireframe";
	if( m_tool >= 0 ) chip += std::string( "   " ) + ICON_FA_MOUNTAIN_SUN " Terrain: " + kTools[m_tool].name + "  (Esc ends)";
	const ImVec2 cs = ImGui::CalcTextSize( chip.c_str() );
	dl->AddRectFilled( ImVec2( ox + 10, oy + 10 ), ImVec2( ox + 26 + cs.x, oy + 18 + cs.y ), IM_COL32( 14, 15, 17, 170 ), 6 );
	dl->AddText( ImVec2( ox + 18, oy + 14 ), IM_COL32( 215, 222, 230, 255 ), chip.c_str() );
	if( m_scene.Entities().size() <= 2 && !m_scene.FirstTerrain() )
	{
		const char* hint = "Empty level - add a Terrain (Terrain menu), drag actors in from Place Actors,\nor File > New Starter Zone for a ready-to-play example.\nHold the right mouse button + W A S D to fly around.";
		const ImVec2 hs = ImGui::CalcTextSize( hint );
		const ImVec2 a( ox + ( m_viewW - hs.x ) * 0.5f, oy + m_viewH * 0.5f - hs.y );
		dl->AddRectFilled( ImVec2( a.x - 14, a.y - 10 ), ImVec2( a.x + hs.x + 14, a.y + hs.y + 10 ), IM_COL32( 14, 15, 17, 190 ), 8 );
		dl->AddText( a, IM_COL32( 220, 225, 232, 255 ), hint );
	}
}

float Editor::CameraSpeedMps() const
{
	static const float speeds[] = { 1.5f, 3, 6, 12, 24, 48, 96, 192 };
	return speeds[std::max( 1, std::min( 8, m_camSpeed ) ) - 1];
}

// Unreal-style: RMB held = fly (mouse looks, W A S D move, Q / E down / up, wheel changes speed), LMB drag = move
// forward / back and turn, MMB drag = pan, Alt+LMB orbit, Alt+RMB dolly, Alt+MMB pan, wheel = dolly, F frames.
// A click (no drag) with LMB selects; with RMB it opens the viewport menu.
void Editor::Navigation( bool hovered, float ox, float oy )
{
	ImGuiIO& io = ImGui::GetIO();
	const float mx = io.MousePos.x - ox, my = io.MousePos.y - oy;
	const float dt = std::min( 0.1f, io.DeltaTime );
	static bool navAlt = false;
	auto fwdOf = [&]() {
		const float cp = std::cos( m_pitch );
		return Vector3( -std::sin( m_yaw ) * cp, std::sin( m_pitch ), -std::cos( m_yaw ) * cp );
	};
	const bool overGizmo = m_gizmoHover && m_scene.Find( m_selected ) && m_gizmoOp > 0;

	// which button drives the camera
	if( hovered && m_navButton < 0 )
	{
		for( int b = 0; b < 3; ++b )
		{
			if( !ImGui::IsMouseClicked( b ) ) continue;
			if( b == 0 && !io.KeyAlt && ( m_tool >= 0 || overGizmo ) ) break;   // a brush stroke or a gizmo drag
			m_navButton = b;
			navAlt = io.KeyAlt;
			m_navMoved = 0;
			m_navUsedKeys = false;
			break;
		}
	}
	m_flying = false;
	if( m_navButton >= 0 )
	{
		const ImVec2 d = io.MouseDelta;
		m_navMoved += std::fabs( d.x ) + std::fabs( d.y );
		const bool dragging = m_navMoved >= 4;
		Vector3 eye = m_pivot - fwdOf() * m_dist;
		const float look = 0.0045f * m_lookSens;
		if( navAlt )
		{
			if( m_navButton == 0 )   // orbit round the pivot
			{
				m_yaw -= d.x * 0.006f * m_lookSens;
				m_pitch = std::max( -1.52f, std::min( 1.52f, m_pitch - d.y * 0.006f * m_lookSens ) );
			}
			else if( m_navButton == 1 )
				m_dist = std::max( 1.0f, m_dist * ( 1.0f - ( d.x - d.y ) * 0.005f ) );
		}
		else if( m_navButton == 1 )   // fly
		{
			m_flying = true;
			m_yaw -= d.x * look;
			m_pitch = std::max( -1.52f, std::min( 1.52f, m_pitch - d.y * look ) );
			const Vector3 f = fwdOf(), right = Normalize( Cross( f, Vector3( 0, 1, 0 ) ) );
			Vector3 move( 0, 0, 0 );
			if( ImGui::IsKeyDown( ImGuiKey_W ) || ImGui::IsKeyDown( ImGuiKey_UpArrow ) ) move += f;
			if( ImGui::IsKeyDown( ImGuiKey_S ) || ImGui::IsKeyDown( ImGuiKey_DownArrow ) ) move = move - f;
			if( ImGui::IsKeyDown( ImGuiKey_D ) || ImGui::IsKeyDown( ImGuiKey_RightArrow ) ) move += right;
			if( ImGui::IsKeyDown( ImGuiKey_A ) || ImGui::IsKeyDown( ImGuiKey_LeftArrow ) ) move = move - right;
			if( ImGui::IsKeyDown( ImGuiKey_E ) || ImGui::IsKeyDown( ImGuiKey_PageUp ) ) move += Vector3( 0, 1, 0 );
			if( ImGui::IsKeyDown( ImGuiKey_Q ) || ImGui::IsKeyDown( ImGuiKey_PageDown ) ) move = move - Vector3( 0, 1, 0 );
			if( LengthSq( move ) > 0 )
			{
				m_navUsedKeys = true;
				eye += Normalize( move ) * ( CameraSpeedMps() * ( io.KeyShift ? 3.0f : 1.0f ) * dt );
			}
			if( io.MouseWheel != 0.0f )
			{
				m_camSpeed = std::max( 1, std::min( 8, m_camSpeed + ( io.MouseWheel > 0 ? 1 : -1 ) ) );
				m_navUsedKeys = true;
			}
			m_pivot = eye + fwdOf() * m_dist;
		}
		else if( m_navButton == 0 && dragging )   // LMB drag: forward / back + turn
		{
			m_yaw -= d.x * look;
			const Vector3 f = fwdOf(), flat = Normalize( Vector3( f.x, 0, f.z ) );
			eye = eye - flat * ( d.y * CameraSpeedMps() * 0.02f );
			m_pivot = eye + f * m_dist;
		}
		if( m_navButton == 2 )   // pan
		{
			const Vector3 f = fwdOf(), right = Normalize( Cross( f, Vector3( 0, 1, 0 ) ) ), up = Cross( right, f );
			const float k = std::max( 0.02f, m_dist * 0.0016f );
			m_pivot = m_pivot - right * ( d.x * k ) + up * ( d.y * k );
		}
		if( !ImGui::IsMouseDown( m_navButton ) )   // released
		{
			if( !navAlt && !dragging && !m_navUsedKeys )
			{
				Vector3 o, dir;
				m_cam.Ray( mx, my, m_viewW, m_viewH, o, dir );
				if( m_navButton == 0 && hovered ) m_selected = m_scene.Pick( o, dir );
				if( m_navButton == 1 && hovered )
				{
					m_contextAt = DropPoint( mx, my );
					if( const uint32_t hit = m_scene.Pick( o, dir ) ) m_selected = hit;
					ImGui::OpenPopup( "##viewctx" );
				}
			}
			m_navButton = -1;
		}
	}
	if( hovered && m_navButton != 1 && io.MouseWheel != 0.0f )   // wheel: dolly toward what you look at
	{
		const float step = std::max( 0.5f, m_dist * 0.12f ) * ( io.MouseWheel > 0 ? 1.0f : -1.0f );
		if( m_dist - step >= 2.0f ) m_dist -= step;
		else m_pivot += fwdOf() * step;   // too close to the pivot: carry it along
	}
	OrbitFromAngles();

	Vector3 o, d;
	m_cam.Ray( mx, my, m_viewW, m_viewH, o, d );
	m_brushHover = false;
	if( m_tool >= 0 && hovered && m_navButton < 0 )
	{
		Vector3 hit;
		if( m_scene.RaycastTerrain( o, d, hit ) )
		{
			m_brushHover = true;
			m_brushPos = hit;
			if( ImGui::IsMouseClicked( 0 ) && !io.KeyAlt ) BeginStroke( hit );
			else if( m_stroke && ImGui::IsMouseDown( 0 ) ) StrokeTo( hit );
		}
	}
	if( m_stroke && !ImGui::IsMouseDown( 0 ) ) EndStroke();
}

void Editor::ViewportContextMenu()
{
	if( !ImGui::BeginPopup( "##viewctx" ) ) return;
	world::Entity* e = m_scene.Find( m_selected );
	if( e )
	{
		ImGui::TextDisabled( "%s  %s", IconOf( e->type ), e->name.c_str() );
		if( ImGui::MenuItem( ICON_FA_CROSSHAIRS "  Focus", "F" ) ) FrameSelected();
		if( ImGui::MenuItem( ICON_FA_COPY "  Copy", "Ctrl+C" ) ) CopySelected();
		if( ImGui::MenuItem( ICON_FA_CLONE "  Duplicate", "Ctrl+D" ) ) DuplicateSelected();
		if( ImGui::MenuItem( ICON_FA_ARROW_DOWN "  Snap to Ground", "End" ) ) SnapSelectedToGround();
		if( ImGui::MenuItem( ICON_FA_OBJECT_GROUP "  Group", "Ctrl+G" ) ) GroupSelected();
		if( ImGui::MenuItem( ICON_FA_BOX "  Save as Prefab" ) ) SavePrefab( e->id, e->name );
		if( ImGui::MenuItem( ICON_FA_TRASH "  Delete", "Del" ) ) DeleteSelected();
		ImGui::Separator();
	}
	if( ImGui::MenuItem( ICON_FA_PASTE "  Paste Here", "Ctrl+V", false, !m_clipboard.empty() ) )
	{
		m_clipboardAt = m_contextAt - Vector3( 2, 0, 2 );
		Paste();
	}
	if( ImGui::BeginMenu( ICON_FA_PLUS "  Place Actor Here" ) )
	{
		PlaceMenuItems( m_contextAt );
		ImGui::EndMenu();
	}
	ImGui::EndPopup();
}

void Editor::GatherPlayInput( bool hovered, float ox, float oy )
{
	ImGuiIO& io = ImGui::GetIO();
	world::PlayInput in = m_injected;
	const bool keys = ( ImGui::IsWindowFocused() || hovered ) && !io.WantTextInput;
	if( keys )
	{
		in.forward |= ImGui::IsKeyDown( ImGuiKey_W ) || ImGui::IsKeyDown( ImGuiKey_UpArrow );
		in.back |= ImGui::IsKeyDown( ImGuiKey_S ) || ImGui::IsKeyDown( ImGuiKey_DownArrow );
		in.turnLeft |= ImGui::IsKeyDown( ImGuiKey_A ) || ImGui::IsKeyDown( ImGuiKey_LeftArrow );
		in.turnRight |= ImGui::IsKeyDown( ImGuiKey_D ) || ImGui::IsKeyDown( ImGuiKey_RightArrow );
		in.strafeLeft |= ImGui::IsKeyDown( ImGuiKey_Q );
		in.strafeRight |= ImGui::IsKeyDown( ImGuiKey_E );
		in.jump |= ImGui::IsKeyDown( ImGuiKey_Space );
		in.run |= io.KeyShift;
		in.tabTarget |= ImGui::IsKeyPressed( ImGuiKey_Tab, false );
		in.interact |= ImGui::IsKeyPressed( ImGuiKey_F, false );
		for( int k = 0; k < 4; ++k )
			if( ImGui::IsKeyPressed( ImGuiKey( ImGuiKey_1 + k ), false ) ) in.ability = k + 1;
	}
	static bool turning = false, orbiting = false;
	static ImVec2 pressAt;
	if( hovered && ImGui::IsMouseClicked( 1 ) ) turning = true;
	if( hovered && ImGui::IsMouseClicked( 0 ) ) { orbiting = true; pressAt = io.MousePos; }
	if( !ImGui::IsMouseDown( 1 ) ) turning = false;
	if( orbiting && ImGui::IsMouseReleased( 0 ) )
	{
		// a click (not a drag) on a creature targets it
		if( std::fabs( io.MousePos.x - pressAt.x ) + std::fabs( io.MousePos.y - pressAt.y ) < 4 )
		{
			float best = 40;
			for( size_t i = 0; i < m_play->Creatures().size(); ++i )
			{
				const auto& c = m_play->Creatures()[i];
				float sx, sy;
				if( c.state == world::Creature::Dead || !m_cam.Project( c.position + Vector3( 0, 0.7f, 0 ), m_viewW, m_viewH, sx, sy ) ) continue;
				const float d = std::hypot( sx + ox - io.MousePos.x, sy + oy - io.MousePos.y );
				if( d < best ) { best = d; m_play->target = int( i ); }
			}
		}
		orbiting = false;
	}
	if( !ImGui::IsMouseDown( 0 ) ) orbiting = false;
	if( turning || orbiting )
	{
		in.turning |= turning;
		in.orbit |= orbiting && !turning;
		in.mouseDX += io.MouseDelta.x;
		in.mouseDY += io.MouseDelta.y;
		if( turning && orbiting ) in.forward = true;   // both buttons: run forward (WoW)
	}
	if( hovered ) in.wheel += -io.MouseWheel;
	if( !m_paused ) m_play->Tick( io.DeltaTime, in );
	m_injected.mouseDX = m_injected.mouseDY = m_injected.wheel = 0;
	m_injected.tabTarget = m_injected.interact = false;
	m_injected.ability = 0;
}

void Editor::Hud( float ox, float oy )
{
	world::PlaySession& s = *m_play;
	ImDrawList* dl = ImGui::GetWindowDrawList();
	const ui::Fonts& F = ui::GetFonts();
	const float W = m_viewW, H = m_viewH;
	auto text = [&]( ImFont* f, float size, ImVec2 p, ImU32 c, const char* t, bool shadow = true ) {
		if( shadow ) dl->AddText( f, size, ImVec2( p.x + 1, p.y + 1 ), IM_COL32( 0, 0, 0, 200 ), t );
		dl->AddText( f, size, p, c, t );
	};
	auto panel = [&]( ImVec2 a, ImVec2 b ) {
		dl->AddRectFilled( a, b, IM_COL32( 16, 17, 20, 205 ), 8 );
		dl->AddRect( a, b, IM_COL32( 255, 255, 255, 22 ), 8 );
	};
	// nameplates + quest markers + floating combat text
	for( size_t i = 0; i < s.Creatures().size(); ++i )
	{
		const auto& c = s.Creatures()[i];
		float sx, sy;
		if( c.state == world::Creature::Dead || !m_cam.Project( c.position + Vector3( 0, 1.9f, 0 ), W, H, sx, sy ) ) continue;
		if( Length( c.position - s.PlayerPosition() ) > 60 ) continue;
		char name[64];
		std::snprintf( name, sizeof( name ), "%s  %d", c.name.c_str(), c.level );
		const ImVec2 ts = ImGui::CalcTextSize( name );
		const bool tgt = int( i ) == s.target;
		text( F.bold, 15, ImVec2( ox + sx - ts.x * 0.5f, oy + sy - 24 ), c.hostile || c.state == world::Creature::Chase ? IM_COL32( 255, 110, 95, 255 ) : IM_COL32( 245, 225, 120, 255 ), name );
		ui::Bar( ImVec2( ox + sx - 36, oy + sy - 6 ), ImVec2( 72, 8 ), c.hp / c.maxHp, IM_COL32( 196, 52, 44, 255 ), nullptr, dl );
		if( tgt ) dl->AddRect( ImVec2( ox + sx - 38, oy + sy - 8 ), ImVec2( ox + sx + 38, oy + sy + 4 ), IM_COL32( 255, 220, 120, 255 ), 4, 0, 1.5f );
	}
	for( const auto& q : s.quests )
	{
		float sx, sy;
		if( !m_cam.Project( s.World().WorldPosition( q.giverId ) + Vector3( 0, 2.9f, 0 ), W, H, sx, sy ) ) continue;
		const char* mark = q.state == world::Quest::Offered ? "!" : q.state == world::Quest::Ready ? "?" : q.state == world::Quest::Active ? "?" : nullptr;
		if( !mark ) continue;
		const ImU32 c = q.state == world::Quest::Active ? IM_COL32( 160, 160, 160, 255 ) : IM_COL32( 255, 210, 40, 255 );
		text( F.huge, 34, ImVec2( ox + sx - 6, oy + sy - 30 ), c, mark );
		const auto* giver = s.World().Find( q.giverId );
		if( giver && m_cam.Project( s.World().WorldPosition( q.giverId ) + Vector3( 0, 2.3f, 0 ), W, H, sx, sy ) )
		{
			const std::string n = giver->props.value( "npc", giver->name );
			const ImVec2 ts = ImGui::CalcTextSize( n.c_str() );
			text( F.bold, 15, ImVec2( ox + sx - ts.x * 0.5f, oy + sy - 4 ), IM_COL32( 120, 230, 120, 255 ), n.c_str() );
		}
	}
	for( const auto& f : s.floats )
	{
		float sx, sy;
		if( !m_cam.Project( f.at, W, H, sx, sy ) ) continue;
		const int a = int( 255 * std::max( 0.0f, 1.0f - f.age / 1.6f ) );
		text( F.big, 24, ImVec2( ox + sx - 10, oy + sy - f.age * 40 ), f.good ? IM_COL32( 120, 240, 120, a ) : IM_COL32( 255, 220, 90, a ), f.text.c_str() );
	}

	// player frame + target frame (top left)
	char buf[128];
	const ImVec2 pf( ox + 16, oy + 16 );
	panel( pf, ImVec2( pf.x + 250, pf.y + 66 ) );
	dl->AddCircleFilled( ImVec2( pf.x + 33, pf.y + 33 ), 24, IM_COL32( 40, 70, 130, 255 ) );
	dl->AddCircle( ImVec2( pf.x + 33, pf.y + 33 ), 24, IM_COL32( 230, 190, 80, 255 ), 0, 2 );
	text( F.big, 24, ImVec2( pf.x + 23, pf.y + 20 ), IM_COL32( 230, 235, 245, 255 ), ICON_FA_USER_SHIELD );
	std::snprintf( buf, sizeof( buf ), "You   Level %d", s.level );
	text( F.bold, 15, ImVec2( pf.x + 66, pf.y + 8 ), IM_COL32( 240, 240, 240, 255 ), buf );
	std::snprintf( buf, sizeof( buf ), "%d / %d", int( s.hp ), int( s.maxHp ) );
	ui::Bar( ImVec2( pf.x + 66, pf.y + 30 ), ImVec2( 172, 16 ), s.hp / s.maxHp, IM_COL32( 46, 170, 70, 255 ), buf, dl );
	ui::Bar( ImVec2( pf.x + 66, pf.y + 50 ), ImVec2( 172, 7 ), float( s.xp ) / float( s.XpToLevel() ), IM_COL32( 140, 80, 210, 255 ), nullptr, dl );
	if( s.target >= 0 && s.target < int( s.Creatures().size() ) )
	{
		const auto& c = s.Creatures()[size_t( s.target )];
		const ImVec2 tf( pf.x + 266, pf.y );
		panel( tf, ImVec2( tf.x + 230, tf.y + 66 ) );
		std::snprintf( buf, sizeof( buf ), "%s   Level %d", c.name.c_str(), c.level );
		text( F.bold, 15, ImVec2( tf.x + 12, tf.y + 8 ), c.hostile || c.state == world::Creature::Chase ? IM_COL32( 255, 120, 100, 255 ) : IM_COL32( 245, 225, 120, 255 ), buf );
		std::snprintf( buf, sizeof( buf ), "%d / %d", int( c.hp ), int( c.maxHp ) );
		ui::Bar( ImVec2( tf.x + 12, tf.y + 32 ), ImVec2( 206, 18 ), c.hp / c.maxHp, IM_COL32( 196, 52, 44, 255 ), buf, dl );
	}

	// minimap (top right)
	const float R = 78;
	const ImVec2 mc( ox + W - R - 18, oy + R + 18 );
	dl->AddCircleFilled( mc, R + 4, IM_COL32( 12, 12, 14, 220 ) );
	dl->AddCircleFilled( mc, R, IM_COL32( 46, 70, 44, 230 ) );
	dl->AddCircle( mc, R + 3, IM_COL32( 190, 160, 90, 255 ), 0, 3 );
	const float scale = R / 70.0f;   // 70 m to the edge
	auto dot = [&]( const Vector3& p, ImU32 c, float r ) {
		const float dx = ( p.x - s.PlayerPosition().x ) * scale, dz = ( p.z - s.PlayerPosition().z ) * scale;
		if( dx * dx + dz * dz > ( R - 4 ) * ( R - 4 ) ) return;
		dl->AddCircleFilled( ImVec2( mc.x + dx, mc.y + dz ), r, c );
	};
	for( const auto& c : s.Creatures() )
		if( c.state != world::Creature::Dead ) dot( c.position, c.hostile ? IM_COL32( 230, 70, 60, 255 ) : IM_COL32( 230, 210, 90, 255 ), 3 );
	for( const auto& q : s.quests ) dot( s.World().WorldPosition( q.giverId ), IM_COL32( 255, 215, 40, 255 ), 4.5f );
	const float yaw = s.PlayerYaw();
	const ImVec2 tip( mc.x - std::sin( yaw ) * 9, mc.y - std::cos( yaw ) * 9 );
	const ImVec2 l( mc.x - std::sin( yaw + 2.5f ) * 7, mc.y - std::cos( yaw + 2.5f ) * 7 ), r( mc.x - std::sin( yaw - 2.5f ) * 7, mc.y - std::cos( yaw - 2.5f ) * 7 );
	dl->AddTriangleFilled( tip, l, r, IM_COL32( 255, 255, 255, 255 ) );
	text( F.bold, 15, ImVec2( mc.x - 5, mc.y - R - 2 ), IM_COL32( 230, 230, 230, 255 ), "N" );
	if( !s.zone.empty() )
	{
		const ImVec2 zs = ImGui::CalcTextSize( s.zone.c_str() );
		text( F.bold, 15, ImVec2( mc.x - zs.x * 0.5f, mc.y + R + 8 ), IM_COL32( 245, 215, 120, 255 ), s.zone.c_str() );
	}

	// quest tracker (right)
	float qy = mc.y + R + 36;
	for( const auto& q : s.quests )
	{
		if( q.state != world::Quest::Active && q.state != world::Quest::Ready ) continue;
		text( F.bold, 15, ImVec2( ox + W - 260, oy + qy - oy ), IM_COL32( 255, 210, 40, 255 ), q.name.c_str() );
		std::snprintf( buf, sizeof( buf ), q.state == world::Quest::Ready ? "  - Return to the quest giver" : "  - %s slain: %d/%d", q.target.c_str(), q.have, q.need );
		text( F.body, 15, ImVec2( ox + W - 260, qy + 20 ), IM_COL32( 230, 230, 230, 255 ), buf );
		qy += 46;
	}

	// action bar (bottom centre)
	const float slot = 50, gap = 6, barW = 4 * slot + 3 * gap;
	const ImVec2 ab( ox + ( W - barW ) * 0.5f, oy + H - slot - 52 );
	panel( ImVec2( ab.x - 10, ab.y - 10 ), ImVec2( ab.x + barW + 10, ab.y + slot + 22 ) );
	for( int i = 0; i < int( s.abilities.size() ) && i < 4; ++i )
	{
		const auto& a = s.abilities[size_t( i )];
		const ImVec2 p( ab.x + i * ( slot + gap ), ab.y );
		ImGui::SetCursorScreenPos( p );
		ImGui::PushID( i );
		if( ImGui::InvisibleButton( "##slot", ImVec2( slot, slot ) ) ) m_injected.ability = i + 1;
		const bool hov = ImGui::IsItemHovered();
		ImGui::PopID();
		dl->AddRectFilledMultiColor( p, ImVec2( p.x + slot, p.y + slot ), IM_COL32( 70, 72, 80, 255 ), IM_COL32( 70, 72, 80, 255 ), IM_COL32( 36, 37, 42, 255 ), IM_COL32( 36, 37, 42, 255 ) );
		const ImU32 ic = a.damage < 0 ? IM_COL32( 120, 230, 130, 255 ) : i == 2 ? IM_COL32( 255, 150, 60, 255 ) : IM_COL32( 230, 220, 200, 255 );
		const ImVec2 is = F.big->CalcTextSizeA( 24, FLT_MAX, 0, AbilityIcon( a.icon ) );
		text( F.big, 24, ImVec2( p.x + ( slot - is.x ) * 0.5f, p.y + ( slot - is.y ) * 0.5f ), ic, AbilityIcon( a.icon ) );
		const float cd = a.cooldown > 0 ? a.remaining / a.cooldown : 0, g = s.gcd / 1.2f, shade = std::max( cd, g );
		if( shade > 0 ) dl->AddRectFilled( ImVec2( p.x, p.y + slot * ( 1 - shade ) ), ImVec2( p.x + slot, p.y + slot ), IM_COL32( 0, 0, 0, 150 ) );
		if( a.remaining > 0.05f )
		{
			std::snprintf( buf, sizeof( buf ), "%.0f", std::ceil( a.remaining ) );
			text( F.bold, 15, ImVec2( p.x + slot * 0.5f - 5, p.y + slot * 0.5f - 9 ), IM_COL32( 255, 255, 255, 255 ), buf );
		}
		dl->AddRect( p, ImVec2( p.x + slot, p.y + slot ), hov ? IM_COL32( 255, 220, 120, 255 ) : IM_COL32( 0, 0, 0, 200 ), 4, 0, hov ? 2.0f : 1.0f );
		std::snprintf( buf, sizeof( buf ), "%d", i + 1 );
		text( F.bold, 15, ImVec2( p.x + 4, p.y + 2 ), IM_COL32( 230, 230, 230, 255 ), buf );
		if( hov )
		{
			ImGui::BeginTooltip();
			ui::PushFont( F.bold );
			ImGui::TextUnformatted( a.name );
			ImGui::PopFont();
			if( a.damage < 0 ) ImGui::Text( "Heals %d. Cooldown %.0f s.", int( -a.damage ), a.cooldown );
			else ImGui::Text( "%d damage, %.0f m range%s.", int( a.damage ), a.range, a.cooldown > 0 ? ( ", cooldown " + std::to_string( int( a.cooldown ) ) + " s" ).c_str() : "" );
			ImGui::EndTooltip();
		}
	}
	ui::Bar( ImVec2( ab.x, ab.y + slot + 6 ), ImVec2( barW, 7 ), float( s.xp ) / float( s.XpToLevel() ), IM_COL32( 140, 80, 210, 255 ), nullptr, dl );

	// zone banner
	if( s.zoneBanner > 0 && !s.zone.empty() )
	{
		const int a = int( 255 * std::min( 1.0f, s.zoneBanner ) );
		const ImVec2 zs = F.huge->CalcTextSizeA( 34, FLT_MAX, 0, s.zone.c_str() );
		text( F.huge, 34, ImVec2( ox + ( W - zs.x ) * 0.5f, oy + H * 0.18f ), IM_COL32( 255, 220, 130, a ), s.zone.c_str() );
		const ImVec2 is = ImGui::CalcTextSize( s.zoneInfo.c_str() );
		text( F.bold, 15, ImVec2( ox + ( W - is.x ) * 0.5f, oy + H * 0.18f + 42 ), IM_COL32( 230, 230, 230, a ), s.zoneInfo.c_str() );
	}
	if( s.deadFor > 0 )
	{
		dl->AddRectFilled( ImVec2( ox, oy ), ImVec2( ox + W, oy + H ), IM_COL32( 40, 0, 0, 110 ) );
		const ImVec2 ds = F.huge->CalcTextSizeA( 34, FLT_MAX, 0, "You died" );
		text( F.huge, 34, ImVec2( ox + ( W - ds.x ) * 0.5f, oy + H * 0.4f ), IM_COL32( 255, 90, 80, 255 ), "You died" );
	}

	// the quest dialog
	if( s.talkingTo >= 0 && s.talkingTo < int( s.quests.size() ) )
	{
		world::Quest& q = s.quests[size_t( s.talkingTo )];
		const auto* giver = s.World().Find( q.giverId );
		ImGui::SetCursorScreenPos( ImVec2( ox + 24, oy + H * 0.28f ) );
		ImGui::PushStyleColor( ImGuiCol_ChildBg, IM_COL32( 26, 22, 18, 236 ) );
		ImGui::PushStyleColor( ImGuiCol_Border, IM_COL32( 190, 150, 80, 255 ) );
		ImGui::BeginChild( "##dialog", ImVec2( 360, 0 ), ImGuiChildFlags_Borders | ImGuiChildFlags_AutoResizeY );
		ui::PushFont( F.big );
		ImGui::TextColored( ImVec4( 1, 0.85f, 0.4f, 1 ), "%s", giver ? giver->props.value( "npc", giver->name ).c_str() : "Quest Giver" );
		ImGui::PopFont();
		ImGui::Separator();
		ui::PushFont( F.bold );
		ImGui::TextUnformatted( q.name.c_str() );
		ImGui::PopFont();
		ImGui::PushTextWrapPos( 0 );
		ImGui::TextUnformatted( q.state == world::Quest::Ready || q.state == world::Quest::Complete ? q.done.c_str() : q.text.c_str() );
		ImGui::PopTextWrapPos();
		ImGui::TextDisabled( "Objective: slay %d %s.  Reward: %d XP", q.need, q.target.c_str(), q.rewardXp );
		ImGui::Spacing();
		if( q.state == world::Quest::Offered && ImGui::Button( ICON_FA_CHECK "  Accept", ImVec2( 120, 0 ) ) ) { s.AcceptQuest( s.talkingTo ); s.talkingTo = -1; }
		if( q.state == world::Quest::Ready && ImGui::Button( ICON_FA_STAR "  Complete Quest", ImVec2( 160, 0 ) ) ) { s.CompleteQuest( s.talkingTo ); s.talkingTo = -1; }
		if( q.state == world::Quest::Active ) ImGui::TextColored( ImVec4( 0.8f, 0.8f, 0.8f, 1 ), "%s slain: %d/%d", q.target.c_str(), q.have, q.need );
		ImGui::SameLine();
		if( ImGui::Button( "Goodbye" ) ) s.talkingTo = -1;
		ImGui::EndChild();
		ImGui::PopStyleColor( 2 );
	}
	// help line
	const char* help = "W/S move  A/D turn  Q/E strafe  Space jump  Tab target  1-4 abilities  F talk  RMB turn  Esc stop";
	const ImVec2 hs = ImGui::CalcTextSize( help );
	text( F.body, 15, ImVec2( ox + ( W - hs.x ) * 0.5f, oy + H - 20 ), IM_COL32( 200, 205, 210, 200 ), help );
}

// ------------------------------------------------------------------------------------------------ scene tree
void Editor::SceneNode( uint32_t id, const std::string& filter )
{
	const auto* e = ( Playing() ? m_play->World() : m_scene ).Find( id );
	if( !e ) return;
	const auto children = ( Playing() ? m_play->World() : m_scene ).Children( id );
	if( !filter.empty() )
	{
		std::string n = e->name, f = filter;
		std::transform( n.begin(), n.end(), n.begin(), ::tolower );
		std::transform( f.begin(), f.end(), f.begin(), ::tolower );
		if( n.find( f ) == std::string::npos )
		{
			for( uint32_t c : children ) SceneNode( c, filter );
			return;
		}
	}
	ImGui::PushID( int( id ) );
	ImGuiTreeNodeFlags flags = ImGuiTreeNodeFlags_OpenOnArrow | ImGuiTreeNodeFlags_SpanAvailWidth | ImGuiTreeNodeFlags_DefaultOpen | ImGuiTreeNodeFlags_FramePadding;
	if( children.empty() ) flags |= ImGuiTreeNodeFlags_Leaf;
	if( id == m_selected ) flags |= ImGuiTreeNodeFlags_Selected;
	const bool open = ImGui::TreeNodeEx( "##node", flags, "" );
	const bool clicked = ImGui::IsItemClicked() && !ImGui::IsItemToggledOpen();
	if( clicked ) m_selected = id;
	if( ImGui::IsItemHovered() && ImGui::IsMouseDoubleClicked( 0 ) ) FrameSelected();
	if( !Playing() && ImGui::BeginDragDropSource() )
	{
		ImGui::SetDragDropPayload( "CMMO_NODE", &id, sizeof( id ) );
		ImGui::Text( "%s %s", IconOf( e->type ), e->name.c_str() );
		ImGui::EndDragDropSource();
	}
	if( !Playing() && ImGui::BeginDragDropTarget() )
	{
		if( const ImGuiPayload* p = ImGui::AcceptDragDropPayload( "CMMO_NODE" ) )
			if( !Reparent( *(const uint32_t*)p->Data, id ) ) Print( "Can't parent an actor to itself or its own child." );
		ImGui::EndDragDropTarget();
	}
	if( !Playing() && ImGui::BeginPopupContextItem() )
	{
		m_selected = id;
		if( ImGui::MenuItem( ICON_FA_PEN "  Rename", "F2" ) ) { m_renaming = id; std::snprintf( m_renameBuf, sizeof( m_renameBuf ), "%s", e->name.c_str() ); }
		if( ImGui::MenuItem( ICON_FA_CLONE "  Duplicate", "Ctrl+D" ) ) DuplicateSelected();
		if( ImGui::MenuItem( ICON_FA_PLUS "  Add Empty Child" ) ) Place( ActorType::Empty, Vector3( 0, 0, 0 ), id );
		if( e->parent && ImGui::MenuItem( ICON_FA_ARROW_UP "  Unparent" ) ) Reparent( id, 0 );
		if( ImGui::MenuItem( ICON_FA_BOX "  Save as Prefab" ) ) SavePrefab( id, e->name );
		if( ImGui::MenuItem( ICON_FA_CROSSHAIRS "  Frame", "F" ) ) FrameSelected();
		ImGui::Separator();
		if( ImGui::MenuItem( ICON_FA_TRASH "  Delete", "Del" ) ) DeleteSelected();
		ImGui::EndPopup();
	}
	// row content: icon, name (or rename field), eye
	ImGui::SameLine( 0, 2 );
	ImGui::PushStyleColor( ImGuiCol_Text, ColorOf( e->type ) );
	ImGui::TextUnformatted( IconOf( e->type ) );
	ImGui::PopStyleColor();
	ImGui::SameLine( 0, 6 );
	if( m_renaming == id && !Playing() )
	{
		ImGui::SetNextItemWidth( ImGui::GetContentRegionAvail().x - 30 );
		ImGui::SetKeyboardFocusHere();
		if( ImGui::InputText( "##rename", m_renameBuf, sizeof( m_renameBuf ), ImGuiInputTextFlags_EnterReturnsTrue | ImGuiInputTextFlags_AutoSelectAll ) )
		{
			if( m_renameBuf[0] ) { m_scene.Find( id )->name = m_renameBuf; Commit( "Rename" ); }
			m_renaming = 0;
		}
		if( ImGui::IsItemDeactivated() ) m_renaming = 0;
	}
	else
	{
		const bool vis = e->visible;
		if( !vis ) ImGui::PushStyleColor( ImGuiCol_Text, ImGui::GetStyle().Colors[ImGuiCol_TextDisabled] );
		ImGui::TextUnformatted( e->name.c_str() );
		if( !vis ) ImGui::PopStyleColor();
	}
	ImGui::SameLine( ImGui::GetWindowContentRegionMax().x - 22 );
	ImGui::PushStyleColor( ImGuiCol_Button, IM_COL32( 0, 0, 0, 0 ) );
	ImGui::PushStyleColor( ImGuiCol_Text, e->visible ? IM_COL32( 170, 178, 190, 255 ) : IM_COL32( 95, 100, 108, 255 ) );
	ImGui::PushStyleVar( ImGuiStyleVar_FramePadding, ImVec2( 2, 0 ) );
	if( ImGui::SmallButton( e->visible ? ICON_FA_EYE : ICON_FA_EYE_SLASH ) && !Playing() )
	{
		m_scene.Find( id )->visible = !e->visible;
		Commit( "Visibility" );
	}
	ImGui::PopStyleVar();
	ImGui::PopStyleColor( 2 );
	if( open )
	{
		for( uint32_t c : children ) SceneNode( c, filter );
		ImGui::TreePop();
	}
	ImGui::PopID();
}

void Editor::ScenePanel()
{
	if( !m_open[PScene] ) return;
	if( !ImGui::Begin( ICON_FA_SITEMAP " Scene", &m_open[PScene] ) ) { ImGui::End(); return; }
	ImGui::SetNextItemWidth( ImGui::GetContentRegionAvail().x - ImGui::GetFrameHeight() - 12 );
	ImGui::InputTextWithHint( "##filter", ICON_FA_MAGNIFYING_GLASS "  Filter actors", m_filter, sizeof( m_filter ) );
	ImGui::SameLine( 0, 6 );
	if( ui::ToolButton( ICON_FA_PLUS, "Add", "Add an actor where the viewport looks." ) ) ImGui::OpenPopup( "##add" );
	if( ImGui::BeginPopup( "##add" ) )
	{
		for( const auto& a : world::Actors() )
			if( ImGui::MenuItem( ( std::string( IconOf( a.type ) ) + "  " + a.label ).c_str() ) ) Place( a.type, PlacementPoint() );
		ImGui::EndPopup();
	}
	ImGui::BeginChild( "##tree", ImVec2( 0, 0 ), ImGuiChildFlags_None );
	ImGui::PushStyleVar( ImGuiStyleVar_ItemSpacing, ImVec2( 4, 2 ) );
	for( uint32_t id : ( Playing() ? m_play->World() : m_scene ).Children( 0 ) ) SceneNode( id, m_filter );
	ImGui::PopStyleVar();
	// drop on empty space: back to the top level
	ImGui::Dummy( ImVec2( ImGui::GetContentRegionAvail().x, std::max( 40.0f, ImGui::GetContentRegionAvail().y ) ) );
	if( !Playing() && ImGui::BeginDragDropTarget() )
	{
		if( const ImGuiPayload* p = ImGui::AcceptDragDropPayload( "CMMO_NODE" ) ) Reparent( *(const uint32_t*)p->Data, 0 );
		ImGui::EndDragDropTarget();
	}
	if( Playing() )
	{
		ui::Section( ICON_FA_DRAGON, "Creatures" );
		for( const auto& c : m_play->Creatures() )
			ImGui::TextColored( c.state == world::Creature::Chase ? ImVec4( 1, 0.45f, 0.4f, 1 ) : c.state == world::Creature::Dead ? ImVec4( 0.5f, 0.5f, 0.5f, 1 ) : ImVec4( 0.8f, 0.8f, 0.8f, 1 ),
								"%s  %s", c.name.c_str(), c.state == world::Creature::Chase ? "(fighting)" : c.state == world::Creature::Dead ? "(dead)" : "" );
	}
	ImGui::EndChild();
	ImGui::End();
}

// ------------------------------------------------------------------------------------------------ inspector
void Editor::InspectorPanel()
{
	if( !m_open[PInspector] ) return;
	if( !ImGui::Begin( ICON_FA_SLIDERS " Inspector", &m_open[PInspector] ) ) { ImGui::End(); return; }
	world::Entity* e = Playing() ? nullptr : m_scene.Find( m_selected );
	if( Playing() ) ImGui::TextDisabled( "Stop playing to edit." );
	else if( !e ) ImGui::TextDisabled( "Select an actor in the viewport or the Scene." );
	else
	{
		bool done = false;
		ImGui::PushStyleColor( ImGuiCol_Text, ColorOf( e->type ) );
		ui::PushFont( ui::GetFonts().big );
		ImGui::TextUnformatted( IconOf( e->type ) );
		ImGui::PopFont();
		ImGui::PopStyleColor();
		ImGui::SameLine();
		ImGui::BeginGroup();
		char name[128];
		std::snprintf( name, sizeof( name ), "%s", e->name.c_str() );
		ImGui::SetNextItemWidth( ImGui::GetContentRegionAvail().x - 30 );
		if( ImGui::InputText( "##name", name, sizeof( name ) ) ) e->name = name;
		done |= ImGui::IsItemDeactivatedAfterEdit();
		ImGui::SameLine();
		if( ImGui::Checkbox( "##vis", &e->visible ) ) done = true;
		ui::Tip( "Visible", "Hidden actors (and their children) are not drawn or played." );
		ImGui::TextDisabled( "%s%s", world::InfoOf( e->type ).label, e->parent && m_scene.Find( e->parent ) ? ( "  -  child of " + m_scene.Find( e->parent )->name ).c_str() : "" );
		ImGui::EndGroup();

		ui::Section( ICON_FA_ARROWS_UP_DOWN_LEFT_RIGHT, "Transform" );
		ui::AxisField( "Location", &e->transform.position.x, 0.1f, &done );
		if( e->type != ActorType::Terrain )
		{
			ui::AxisField( "Rotation", &e->transform.rotation.x, 0.5f, &done );
			ui::AxisField( "Scale", &e->transform.scale.x, 0.02f, &done );
		}
		ui::Section( IconOf( e->type ), world::InfoOf( e->type ).label );
		if( e->type == ActorType::Mesh )
		{
			static const char* shapes[] = { "cube", "sphere", "cylinder", "cone", "plane" };
			std::string shape = e->props.value( "shape", std::string( "cube" ) );
			ui::Label( "Shape" );
			if( ImGui::BeginCombo( "##shape", shape.c_str() ) )
			{
				for( const char* s : shapes )
					if( ImGui::Selectable( s, shape == s ) ) { e->props["shape"] = s; done = true; }
				ImGui::EndCombo();
			}
		}
		if( e->type == ActorType::Model )
		{
			std::string path = e->props.value( "path", std::string() );
			ui::Label( "Model" );
			if( ImGui::BeginCombo( "##model", path.empty() ? "(none)" : path.c_str() ) )
			{
				std::error_code ec;
				for( const auto& f : fs::directory_iterator( fs::path( m_settings.contentDir ) / "models", ec ) )
				{
					const std::string rel = "models/" + f.path().filename().string();
					if( ( EndsWith( rel, ".glb" ) || EndsWith( rel, ".gltf" ) ) && ImGui::Selectable( rel.c_str(), rel == path ) ) { e->props["path"] = rel; done = true; }
				}
				ImGui::EndCombo();
			}
		}
		for( auto it = e->props.begin(); it != e->props.end(); ++it )
		{
			const std::string key = it.key();
			if( key == "shape" || key == "path" ) continue;
			auto& v = it.value();
			ImGui::PushID( key.c_str() );
			const std::string label = Pretty( key );
			if( !v.is_boolean() ) ui::Label( label.c_str() );
			if( v.is_boolean() )
			{
				bool b = v.get<bool>();
				if( ImGui::Checkbox( label.c_str(), &b ) ) { v = b; done = true; }
			}
			else if( v.is_number_integer() )
			{
				int i = v.get<int>();
				if( ImGui::DragInt( "##v", &i, 0.1f, 0, 100000 ) ) v = i;
				done |= ImGui::IsItemDeactivatedAfterEdit();
			}
			else if( v.is_number() )
			{
				float f = v.get<float>();
				if( ImGui::DragFloat( "##v", &f, 0.05f ) ) v = f;
				done |= ImGui::IsItemDeactivatedAfterEdit();
			}
			else if( v.is_string() && v.get<std::string>().size() == 7 && v.get<std::string>()[0] == '#' )
			{
				Vector3 c = world::HexColor( v.get<std::string>() );
				if( ImGui::ColorEdit3( "##v", &c.x, ImGuiColorEditFlags_NoInputs ) ) v = world::ToHex( c );
				done |= ImGui::IsItemDeactivatedAfterEdit();
			}
			else if( v.is_string() )
			{
				char buf[1024];
				std::snprintf( buf, sizeof( buf ), "%s", v.get<std::string>().c_str() );
				const bool multi = key == "text" || key == "done";
				if( multi ? ImGui::InputTextMultiline( "##v", buf, sizeof( buf ), ImVec2( -FLT_MIN, 64 ) ) : ImGui::InputText( "##v", buf, sizeof( buf ) ) ) v = std::string( buf );
				done |= ImGui::IsItemDeactivatedAfterEdit();
			}
			else if( v.is_array() && v.size() == 3 )
			{
				float a[3] = { v[0].get<float>(), v[1].get<float>(), v[2].get<float>() };
				if( ui::AxisField( label.c_str(), a, 0.1f, &done ) ) v = { a[0], a[1], a[2] };
			}
			ImGui::PopID();
		}
		if( e->terrain )
			ImGui::TextDisabled( "%d x %d over %.0f m, %d foliage. Edit it in the Terrain panel.", e->terrain->Res(), e->terrain->Res(), e->terrain->Size(), int( e->terrain->Foliage().size() ) );
		ImGui::Spacing();
		ImGui::Separator();
		if( ui::ToolButton( ICON_FA_CLONE, "Duplicate", "Ctrl+D" ) ) DuplicateSelected();
		ImGui::SameLine( 0, 4 );
		if( ui::ToolButton( ICON_FA_BOX, "Save as Prefab", "Saves this actor and its children to the Content Browser's prefabs." ) ) SavePrefab( e->id, e->name );
		ImGui::SameLine( 0, 4 );
		if( ui::ToolButton( ICON_FA_TRASH, "Delete", "Del", false, 0, ui::col::Stop ) ) { DeleteSelected(); ImGui::End(); return; }
		if( done ) Commit( "Edit" );
	}
	ImGui::End();
}

// ------------------------------------------------------------------------------------------------ place actors
void Editor::PlacePanel()
{
	if( !m_open[PPlace] ) return;
	if( !ImGui::Begin( ICON_FA_PLUS " Place Actors", &m_open[PPlace] ) ) { ImGui::End(); return; }
	ImGui::TextDisabled( "Drag into the viewport, or click to place in view." );
	ImGui::BeginDisabled( Playing() );
	for( const char* group : { "Gameplay", "World", "Basic", "Lighting" } )
	{
		ui::Section( std::string( group ) == "Gameplay" ? ICON_FA_GAMEPAD : std::string( group ) == "World" ? ICON_FA_EARTH_AMERICAS : std::string( group ) == "Lighting" ? ICON_FA_LIGHTBULB : ICON_FA_SHAPES, group );
		for( const auto& a : world::Actors() )
		{
			if( std::string( a.group ) != group ) continue;
			if( ui::WideButton( IconOf( a.type ), a.label, a.what ) ) Place( a.type, PlacementPoint() );
			if( ImGui::BeginDragDropSource() )
			{
				const int t = int( a.type );
				ImGui::SetDragDropPayload( "CMMO_ACTOR", &t, sizeof( t ) );
				ImGui::Text( "%s  %s", IconOf( a.type ), a.label );
				ImGui::EndDragDropSource();
			}
		}
	}
	ImGui::EndDisabled();
	ImGui::End();
}

// ------------------------------------------------------------------------------------------------ terrain (Terrain3D-style)
void Editor::TerrainPanel()
{
	static int lastTool = -1;
	if( m_tool >= 0 && lastTool < 0 )   // a terrain tool turned on: show its settings
	{
		m_open[PTerrain] = true;
		ImGui::SetNextWindowFocus();
	}
	lastTool = m_tool;
	if( !m_open[PTerrain] ) return;
	if( !ImGui::Begin( ICON_FA_MOUNTAIN_SUN " Terrain", &m_open[PTerrain] ) ) { ImGui::End(); return; }
	ImGui::BeginDisabled( Playing() );
	uint32_t tid = 0;
	world::Terrain* t = m_scene.FirstTerrain( &tid );
	static const char* sizes[] = { "128 m", "256 m", "512 m", "1024 m" };
	static const float sizeV[] = { 128, 256, 512, 1024 };
	static const char* resNames[] = { "64 x 64", "128 x 128", "256 x 256", "512 x 512" };
	static const int resV[] = { 64, 128, 256, 512 };
	if( !t )
	{
		ui::Section( ICON_FA_PLUS, "Create Terrain" );
		ImGui::TextWrapped( "This level has no ground yet. Start flat and sculpt, or generate hills from noise and refine them." );
		ui::Label( "Size" );
		ImGui::Combo( "##Size", &m_newSize, sizes, 4 );
		ui::Label( "Resolution" );
		ImGui::Combo( "##Resolution", &m_newRes, resNames, 4 );
		if( ui::WideButton( ICON_FA_SQUARE, "Flat Terrain", "A flat ground plane to sculpt." ) ) CreateTerrain( sizeV[m_newSize], resV[m_newRes], false );
		if( ui::WideButton( ICON_FA_DICE, "Generate from Noise", "Hills and valleys from the settings below." ) ) CreateTerrain( sizeV[m_newSize], resV[m_newRes], true );
	}
	else
	{
		ui::Section( ICON_FA_TOOLBOX, "Tools" );
		const float bw = ImGui::GetFrameHeight() + 8;
		const int perRow = std::max( 1, int( ( ImGui::GetContentRegionAvail().x + 4 ) / ( bw + 4 ) ) );
		for( int i = 0; i < int( sizeof( kTools ) / sizeof( kTools[0] ) ); ++i )
		{
			if( i % perRow ) ImGui::SameLine( 0, 4 );
			if( ui::ToolButton( kTools[i].icon, kTools[i].name, kTools[i].what, m_tool == int( kTools[i].mode ) ) ) m_tool = m_tool == int( kTools[i].mode ) ? -1 : int( kTools[i].mode );
		}
		ui::Section( ICON_FA_CIRCLE_DOT, "Brush" );
		ui::Label( "Size" );
		ImGui::SliderFloat( "##Size", &m_brush.radius, 0.5f, 60.0f, "%.1f m" );
		ui::Label( "Strength" );
		ImGui::SliderFloat( "##Strength", &m_brush.strength, 0.02f, 2.0f, "%.2f" );
		static const char* falloffs[] = { "Smooth", "Linear", "Constant", "Sharp" };
		int fo = int( m_brush.falloff );
		ui::Label( "Falloff" );
		if( ImGui::Combo( "##Falloff", &fo, falloffs, 4 ) ) m_brush.falloff = world::Brush::Falloff( fo );
		if( m_tool == world::Brush::Paint || m_tool < 0 )
		{
			ui::Section( ICON_FA_LAYER_GROUP, "Texture Layers" );
			for( int l = 0; l < world::Terrain::kLayers; ++l )
			{
				ImGui::PushID( l );
				if( ImGui::RadioButton( "##l", m_brush.layer == l ) ) { m_brush.layer = l; m_tool = world::Brush::Paint; }
				ImGui::SameLine();
				if( ImGui::ColorEdit3( "##c", &t->layers[l].color.x, ImGuiColorEditFlags_NoInputs ) ) t->ShadingChanged();
				if( ImGui::IsItemDeactivatedAfterEdit() ) Commit( "Layer" );
				ImGui::SameLine();
				ImGui::TextUnformatted( t->layers[l].name.c_str() );
				ImGui::PopID();
			}
			if( ImGui::Checkbox( "Auto-shader (rock on slopes, snow up high)", &t->autoShader ) ) { t->ShadingChanged(); Commit( "Auto-shader" ); }
			if( t->autoShader )
			{
				ui::Label( "Rock above" );
		if( ImGui::SliderFloat( "##Rock above", &t->slopeDeg, 10, 70, "%.0f deg" ) ) t->ShadingChanged();
				if( ImGui::IsItemDeactivatedAfterEdit() ) Commit( "Auto-shader" );
				ui::Label( "Snow above" );
		if( ImGui::SliderFloat( "##Snow above", &t->snowHeight, 0, 200, "%.0f m" ) ) t->ShadingChanged();
				if( ImGui::IsItemDeactivatedAfterEdit() ) Commit( "Auto-shader" );
			}
		}
		if( m_tool == world::Brush::Foliage || m_tool == world::Brush::EraseFoliage || m_tool < 0 )
		{
			ui::Section( ICON_FA_TREE, "Foliage" );
			const char* icons[] = { ICON_FA_TREE, ICON_FA_CHESS_PAWN, ICON_FA_SEEDLING, ICON_FA_GEM, ICON_FA_WHEAT_AWN };
			for( int k = 0; k < int( world::FoliageKind::Count ); ++k )
			{
				if( k ) ImGui::SameLine( 0, 4 );
				if( ui::ToolButton( icons[k], world::FoliageName( world::FoliageKind( k ) ), "Paint this kind with the Foliage tool.", m_brush.foliage == world::FoliageKind( k ) ) )
				{
					m_brush.foliage = world::FoliageKind( k );
					if( m_tool != world::Brush::EraseFoliage ) m_tool = world::Brush::Foliage;
				}
			}
			ui::Label( "Density" );
		ImGui::SliderFloat( "##Density", &m_brush.density, 0.05f, 2.0f );
			ImGui::Text( "%d instances", int( t->Foliage().size() ) );
			ImGui::SameLine();
			if( ImGui::SmallButton( "Clear all" ) ) { t->ClearFoliage(); Commit( "Clear foliage" ); }
		}
	}
	ui::Section( ICON_FA_DICE, "Generate" );
	ui::Label( "Seed" );
		ImGui::DragInt( "##Seed", &m_genSeed, 1, 1, 99999 );
	ui::Label( "Height" );
		ImGui::SliderFloat( "##Height", &m_genHeight, 2, 150, "%.0f m" );
	ui::Label( "Feature size" );
		ImGui::SliderFloat( "##Feature size", &m_genFeature, 8, 200, "%.0f m" );
	ui::Label( "Detail" );
		ImGui::SliderInt( "##Detail", &m_genOctaves, 1, 8 );
	if( t )
	{
		if( ui::WideButton( ICON_FA_ARROWS_ROTATE, "Replace heights", "Regenerate the whole terrain from these settings (undo brings it back)." ) )
		{
			t->Generate( uint32_t( m_genSeed ), m_genHeight, m_genFeature, m_genOctaves, false );
			Commit( "Generate" );
		}
		if( ui::WideButton( ICON_FA_PLUS, "Add on top", "Add the noise to the current heights." ) )
		{
			t->Generate( uint32_t( m_genSeed ), m_genHeight * 0.4f, m_genFeature, m_genOctaves, true );
			Commit( "Generate" );
		}
	}
	ImGui::EndDisabled();
	ImGui::End();
}

// ------------------------------------------------------------------------------------------------ content browser
void Editor::ContentPanel()
{
	if( !m_open[PContent] ) return;
	if( !ImGui::Begin( ICON_FA_FOLDER_OPEN " Content Browser", &m_open[PContent] ) ) { ImGui::End(); return; }
	const char* tabs[] = { ICON_FA_MAP "  Levels", ICON_FA_CHESS_ROOK "  Models", ICON_FA_BOX "  Prefabs" };
	const char* subs[] = { "levels", "models", "prefabs" };
	ImGui::BeginChild( "##folders", ImVec2( 150, 0 ), ImGuiChildFlags_Borders );
	for( int i = 0; i < 3; ++i )
		if( ImGui::Selectable( tabs[i], m_contentTab == i ) ) m_contentTab = i;
	ImGui::Spacing();
	ImGui::TextDisabled( "%s", m_settings.contentDir.c_str() );
	ImGui::EndChild();
	ImGui::SameLine();
	ImGui::BeginChild( "##files" );
	if( m_contentTab == 0 )
	{
		ImGui::SetNextItemWidth( 180 );
		ImGui::InputTextWithHint( "##save", "level name", m_saveName, sizeof( m_saveName ) );
		ImGui::SameLine();
		if( ImGui::Button( ICON_FA_FLOPPY_DISK "  Save As" ) ) SaveLevel( ( fs::path( m_settings.contentDir ) / "levels" / ( std::string( m_saveName ) + ".level.json" ) ).string() );
	}
	else if( m_contentTab == 1 )
		ImGui::TextDisabled( "Put .glb / .gltf files in %s (for example Forge exports) - they appear here.", ( fs::path( m_settings.contentDir ) / "models" ).string().c_str() );
	else
	{
		ImGui::SetNextItemWidth( 180 );
		ImGui::InputTextWithHint( "##pf", "prefab name", m_prefabName, sizeof( m_prefabName ) );
		ImGui::SameLine();
		ImGui::BeginDisabled( !m_scene.Find( m_selected ) );
		if( ImGui::Button( ICON_FA_BOX "  Save Selection" ) ) SavePrefab( m_selected, m_prefabName );
		ImGui::EndDisabled();
	}
	ImGui::Separator();
	const float tile = 104;
	const int cols = std::max( 1, int( ImGui::GetContentRegionAvail().x / ( tile + 10 ) ) );
	int n = 0;
	std::error_code ec;
	std::vector<fs::path> files;
	for( const auto& f : fs::directory_iterator( fs::path( m_settings.contentDir ) / subs[m_contentTab], ec ) ) files.push_back( f.path() );
	std::sort( files.begin(), files.end() );
	for( const auto& p : files )
	{
		const std::string fn = p.filename().string();
		const bool ok = m_contentTab == 0 ? EndsWith( fn, ".level.json" ) : m_contentTab == 1 ? ( EndsWith( fn, ".glb" ) || EndsWith( fn, ".gltf" ) ) : EndsWith( fn, ".prefab.json" );
		if( !ok ) continue;
		const std::string rel = std::string( subs[m_contentTab] ) + "/" + fn;
		if( n % cols ) ImGui::SameLine( 0, 10 );
		ImGui::PushID( fn.c_str() );
		ImGui::BeginGroup();
		const ImVec2 a = ImGui::GetCursorScreenPos();
		const bool clicked = ImGui::InvisibleButton( "##tile", ImVec2( tile, tile ) );
		const bool hov = ImGui::IsItemHovered();
		ImDrawList* dl = ImGui::GetWindowDrawList();
		dl->AddRectFilledMultiColor( a, ImVec2( a.x + tile, a.y + tile ), hov ? IM_COL32( 64, 68, 76, 255 ) : IM_COL32( 48, 50, 56, 255 ), hov ? IM_COL32( 64, 68, 76, 255 ) : IM_COL32( 48, 50, 56, 255 ),
									 IM_COL32( 32, 33, 37, 255 ), IM_COL32( 32, 33, 37, 255 ) );
		dl->AddRect( a, ImVec2( a.x + tile, a.y + tile ), hov ? ui::col::Accent : IM_COL32( 0, 0, 0, 160 ), 6 );
		const char* icon = m_contentTab == 0 ? ICON_FA_MAP : m_contentTab == 1 ? ICON_FA_CHESS_ROOK : ICON_FA_BOX;
		const ImU32 ic = m_contentTab == 0 ? IM_COL32( 240, 196, 70, 255 ) : m_contentTab == 1 ? IM_COL32( 190, 150, 240, 255 ) : IM_COL32( 120, 196, 240, 255 );
		const ImVec2 is = ui::GetFonts().huge->CalcTextSizeA( 34, FLT_MAX, 0, icon );
		dl->AddText( ui::GetFonts().big, 34, ImVec2( a.x + ( tile - is.x ) * 0.5f, a.y + 18 ), ic, icon );
		std::string label = fn.substr( 0, fn.find( '.' ) );
		if( label.size() > 13 ) label = label.substr( 0, 12 ) + "...";
		const ImVec2 ls = ImGui::CalcTextSize( label.c_str() );
		dl->AddText( ImVec2( a.x + ( tile - ls.x ) * 0.5f, a.y + tile - ls.y - 10 ), ui::col::Text, label.c_str() );
		if( hov ) ui::Tip( fn.c_str(), m_contentTab == 0 ? "Double-click to open." : "Double-click to place in view, or drag into the viewport." );
		if( ImGui::BeginDragDropSource() )
		{
			ImGui::SetDragDropPayload( "CMMO_ASSET", rel.c_str(), rel.size() + 1 );
			ImGui::Text( "%s %s", icon, fn.c_str() );
			ImGui::EndDragDropSource();
		}
		if( hov && ImGui::IsMouseDoubleClicked( 0 ) )
		{
			if( m_contentTab == 0 ) OpenLevel( p.string() );
			else if( m_contentTab == 1 ) PlaceModel( rel, PlacementPoint() );
			else PlacePrefab( rel, PlacementPoint() );
		}
		(void)clicked;
		ImGui::EndGroup();
		ImGui::PopID();
		++n;
	}
	if( !n ) ImGui::TextDisabled( "Nothing here yet." );
	ImGui::EndChild();
	ImGui::End();
}

void Editor::WorldPanel()
{
	if( !m_open[PWorld] ) return;
	if( !ImGui::Begin( ICON_FA_GLOBE " World Settings", &m_open[PWorld] ) ) { ImGui::End(); return; }
	ImGui::BeginDisabled( Playing() );
	auto& ws = m_scene.settings;
	bool done = false;
	char name[128];
	std::snprintf( name, sizeof( name ), "%s", ws.value( "name", std::string( "New World" ) ).c_str() );
	ui::Label( "World name" );
	if( ImGui::InputText( "##wn", name, sizeof( name ) ) ) ws["name"] = std::string( name );
	done |= ImGui::IsItemDeactivatedAfterEdit();
	ui::Section( ICON_FA_CLOUD_SUN, "Sky & Atmosphere" );
	for( const char* key : { "sky", "horizon", "ambient" } )
	{
		Vector3 c = world::HexColor( ws.value( key, std::string( "#808080" ) ) );
		ui::Label( Pretty( key ).c_str() );
		if( ImGui::ColorEdit3( ( std::string( "##" ) + key ).c_str(), &c.x, ImGuiColorEditFlags_NoInputs ) ) ws[key] = world::ToHex( c );
		done |= ImGui::IsItemDeactivatedAfterEdit();
	}
	float fog = ws.value( "fog", 0.0035f );
	ui::Label( "Fog" );
		if( ImGui::SliderFloat( "##Fog", &fog, 0.0f, 0.03f, "%.4f" ) ) ws["fog"] = fog;
	done |= ImGui::IsItemDeactivatedAfterEdit();
	ui::Section( ICON_FA_PERSON_RUNNING, "Gameplay" );
	float g = ws.value( "gravity", 20.0f );
	ui::Label( "Gravity" );
		if( ImGui::SliderFloat( "##Gravity", &g, 2.0f, 40.0f, "%.1f m/s2" ) ) ws["gravity"] = g;
	done |= ImGui::IsItemDeactivatedAfterEdit();
	ImGui::TextDisabled( "Player speed, jump and camera distance are on the Player Start." );
	if( done ) Commit( "World settings" );
	ImGui::EndDisabled();
	ImGui::End();
}

void Editor::OutputPanel()
{
	if( !m_open[POutput] ) return;
	if( !ImGui::Begin( ICON_FA_TERMINAL " Output", &m_open[POutput] ) ) { ImGui::End(); return; }
	if( ImGui::SmallButton( ICON_FA_BROOM " Clear" ) ) m_log.clear();
	ImGui::Separator();
	ImGui::BeginChild( "##log" );
	for( const auto& line : m_log )
	{
		const bool bad = line.find( "failed" ) != std::string::npos || line.find( "died" ) != std::string::npos || line.find( "Can't" ) != std::string::npos;
		const bool good = line.find( "complete" ) != std::string::npos || line.find( "Level up" ) != std::string::npos || line.find( "Saved" ) != std::string::npos;
		ImGui::TextColored( bad ? ImVec4( 1, 0.5f, 0.45f, 1 ) : good ? ImVec4( 0.5f, 0.9f, 0.55f, 1 ) : ImVec4( 0.82f, 0.84f, 0.87f, 1 ), "%s", line.c_str() );
	}
	if( ImGui::GetScrollY() >= ImGui::GetScrollMaxY() - 4 ) ImGui::SetScrollHereY( 1.0f );
	ImGui::EndChild();
	ImGui::End();
}
}

namespace cmmo::editor
{
void Editor::ControlsPanel()
{
	if( !m_open[PControls] ) return;
	ImGui::SetNextWindowSize( ImVec2( 560, 520 ), ImGuiCond_FirstUseEver );
	if( !ImGui::Begin( ICON_FA_KEYBOARD " Controls", &m_open[PControls] ) ) { ImGui::End(); return; }
	auto table = [&]( const char* icon, const char* title, std::initializer_list<std::pair<const char*, const char*>> rows ) {
		ui::Section( icon, title );
		if( ImGui::BeginTable( title, 2, ImGuiTableFlags_RowBg | ImGuiTableFlags_SizingStretchProp ) )
		{
			for( const auto& r : rows )
			{
				ImGui::TableNextRow();
				ImGui::TableNextColumn();
				ImGui::TextColored( ImVec4( 0.55f, 0.75f, 1, 1 ), "%s", r.first );
				ImGui::TableNextColumn();
				ImGui::TextUnformatted( r.second );
			}
			ImGui::EndTable();
		}
	};
	table( ICON_FA_VIDEO, "Viewport camera (like Unreal)",
		   { { "Hold RMB + W A S D", "fly forward / left / back / right" },
			 { "Hold RMB + Q / E", "fly down / up" },
			 { "Hold RMB + mouse", "look around" },
			 { "Hold RMB + wheel", "camera speed slower / faster" },
			 { "Shift (while flying)", "3x faster" },
			 { "LMB drag", "move forward / back and turn" },
			 { "MMB drag", "pan" },
			 { "Wheel", "move toward what you look at" },
			 { "Alt + LMB / RMB / MMB", "orbit / dolly / pan" },
			 { "F", "focus the selection" } } );
	table( ICON_FA_ARROW_POINTER, "Editing",
		   { { "LMB click", "select   (RMB click: viewport menu)" },
			 { "Q  W  E  R", "select / move / rotate / scale" },
			 { "Ctrl+C / X / V / D", "copy / cut / paste / duplicate" },
			 { "Ctrl+G", "group into an Empty" },
			 { "Del", "delete" },
			 { "End", "snap to the ground" },
			 { "H", "hide / show" },
			 { "F2", "rename" },
			 { "Ctrl+Z / Ctrl+Shift+Z", "undo / redo" },
			 { "Ctrl+S", "save the level" },
			 { "Esc", "stop the terrain tool" } } );
	table( ICON_FA_GAMEPAD, "Play (Alt+P)",
		   { { "W / S, A / D, Q / E", "move, turn, strafe" },
			 { "Space / Shift", "jump / run" },
			 { "RMB drag / LMB drag", "turn the character / look around" },
			 { "Tab, LMB on a creature", "target" },
			 { "1  2  3  4", "Strike, Heroic Blow, Fireball, Mend" },
			 { "F", "talk to a quest giver" },
			 { "Esc", "close the dialog, then stop" } } );
	ImGui::TextDisabled( "On a Mac, Ctrl is Cmd." );
	ImGui::End();
}

void Editor::PrefsPanel()
{
	if( !m_open[PPrefs] ) return;
	ImGui::SetNextWindowSize( ImVec2( 420, 260 ), ImGuiCond_FirstUseEver );
	if( !ImGui::Begin( ICON_FA_GEAR " Editor Preferences", &m_open[PPrefs] ) ) { ImGui::End(); return; }
	ui::Section( ICON_FA_VIDEO, "Camera" );
	ui::Label( "Speed" );
	ImGui::SliderInt( "##speed", &m_camSpeed, 1, 8 );
	ImGui::TextDisabled( "%.1f m/s while flying (hold RMB + W A S D)", CameraSpeedMps() );
	ui::Label( "Mouse look" );
	ImGui::SliderFloat( "##look", &m_lookSens, 0.25f, 3.0f, "%.2f" );
	ui::Section( ICON_FA_MAGNET, "Snapping" );
	ImGui::Checkbox( "Snap moves to the grid", &m_snap );
	ui::Label( "Grid step" );
	ImGui::DragFloat( "##snapmove", &m_snapMove, 0.05f, 0.1f, 50.0f, "%.2f m" );
	ui::Section( ICON_FA_DISPLAY, "Viewport" );
	ImGui::Checkbox( "Grid", &m_grid );
	ImGui::SameLine();
	ImGui::Checkbox( "Stats", &m_stats );
	ImGui::End();
}
}
