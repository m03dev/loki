// MODULE: world
// The engine's world model - everything the editor edits and Play simulates, with no graphics and no UI.
// All vectors and matrices are Carbon math (carbonengine/math): Vector3, Matrix.
//
//   Scene        entities in a hierarchy (parent / children, like Godot's scene tree), a transform, a type and a JSON
//                property bag; world settings (sky, fog, sun time, gravity)
//   Terrain      Terrain3D-style: height grid, 4 texture layers (weights) + an auto-shader (rock on slopes, snow up
//                high), foliage instances; brushes: raise, lower, smooth, flatten, ramp, noise, paint layer, foliage
//   PlaySession  Play in Editor on a COPY of the scene: third-person player (WoW controls) and the MMO gameplay
//                layer - targeting, combat, health / XP / levels, creatures (wander, aggro, leash, respawn), quest
//                givers (kill quests), zones (name banner, level range, PvP flag)
//   Level files  Scene <-> JSON ("cmmo-level" v2, reads v1)
//
// Swap points: the networked server simulation (python/cmmo) can replace PlaySession; the editor only uses its API.
#pragma once

#include <cstdint>
#include <memory>
#include <random>
#include <string>
#include <vector>

#include <nlohmann/json.hpp>

#include "Matrix.h"
#include "Vector3.h"

namespace cmmo::world
{
using json = nlohmann::json;

// ------------------------------------------------------------------------------------------------ actor types
enum class ActorType
{
	Empty,
	Mesh,           // a primitive shape - level blockout
	PointLight,
	DirLight,
	PlayerStart,
	CreatureSpawn,
	TriggerBox,
	Terrain,
	QuestGiver,     // an NPC with a kill quest
	Zone,           // a named area: entering shows its name, level range, PvP
	Model,          // a .glb / .gltf from the Content Browser
	Count
};

struct ActorInfo
{
	ActorType type;
	const char* id;       // stable name in level files
	const char* label;    // shown in the editor
	const char* what;     // tooltip
	const char* group;    // Place Actors section
};
const std::vector<ActorInfo>& Actors();
const ActorInfo& InfoOf( ActorType type );
ActorType TypeFromId( const std::string& id );
json DefaultProps( ActorType type );
json DefaultWorldSettings();

struct Transform
{
	Vector3 position{ 0.0f, 0.0f, 0.0f };   // local (relative to the parent)
	Vector3 rotation{ 0.0f, 0.0f, 0.0f };   // degrees, X then Y then Z
	Vector3 scale{ 1.0f, 1.0f, 1.0f };
	Matrix Local() const;                    // Carbon row-vector convention: v * Local
};

// ------------------------------------------------------------------------------------------------ terrain
enum class FoliageKind : uint8_t
{
	Tree,
	Pine,
	Bush,
	Rock,
	Grass,
	Count
};
const char* FoliageName( FoliageKind k );

struct FoliageInstance
{
	float x, z;          // local to the terrain
	float scale, yaw;
	FoliageKind kind;
};

struct Brush
{
	enum Mode { Raise, Lower, Smooth, Flatten, Ramp, Noise, Paint, Foliage, EraseFoliage, ModeCount } mode = Raise;
	enum Falloff { Smoothstep, Linear, Constant, Sharp } falloff = Smoothstep;
	float radius = 6.0f;
	float strength = 0.4f;
	int layer = 1;                        // Paint: texture layer 0..3
	FoliageKind foliage = FoliageKind::Tree;
	float density = 0.5f;                 // Foliage: instances per dab ~ density * area / 20 m^2
	float height = 0.0f;                  // Flatten target (local)
	Vector3 rampFrom, rampTo;             // Ramp: world drag start / current (heights from where the drag started)
	float rampFromH = 0.0f, rampToH = 0.0f;
	uint32_t seed = 1;
};

struct TerrainLayer
{
	std::string name;
	Vector3 color;
};

class Terrain
{
public:
	static constexpr int kLayers = 4;
	Terrain( int res = 128, float size = 256.0f );
	int Res() const { return m_res; }
	float Size() const { return m_size; }
	int VertexCount() const { return ( m_res + 1 ) * ( m_res + 1 ); }
	const std::vector<float>& Heights() const { return m_h; }
	const std::vector<uint8_t>& Weights() const { return m_w; }          // 4 per vertex, sum 255
	const std::vector<FoliageInstance>& Foliage() const { return m_foliage; }
	uint32_t Version() const { return m_version; }                         // heights / paint changed
	uint32_t FoliageVersion() const { return m_foliageVersion; }

	TerrainLayer layers[kLayers] = { { "Grass", Vector3( 0.30f, 0.47f, 0.19f ) }, { "Dirt", Vector3( 0.46f, 0.34f, 0.22f ) },
									 { "Rock", Vector3( 0.47f, 0.47f, 0.46f ) }, { "Snow", Vector3( 0.92f, 0.94f, 0.96f ) } };
	bool autoShader = true;        // rock on slopes steeper than slopeDeg, snow above snowHeight
	float slopeDeg = 38.0f;
	float snowHeight = 40.0f;
	uint32_t ShadingVersion() const { return m_shadeVersion; }
	void ShadingChanged() { ++m_shadeVersion; }

	bool Inside( float x, float z ) const;
	float HeightAt( float x, float z ) const;          // bilinear; 0 outside
	Vector3 NormalAt( float x, float z ) const;
	Vector3 ColorAt( int i, int j ) const;             // layers + auto-shader, for the renderer
	int Sculpt( float x, float z, const Brush& brush );   // returns vertices / instances changed
	void Generate( uint32_t seed, float height, float featureSize, int octaves, bool add );
	bool Raycast( const Vector3& origin, const Vector3& dir, float maxDist, Vector3& hit ) const;
	void ClearFoliage();

	json Save() const;
	bool Load( const json& t );

private:
	float Falloff( float d, float r, Brush::Falloff f ) const;
	int m_res;
	float m_size;
	std::vector<float> m_h;
	std::vector<uint8_t> m_w;
	std::vector<FoliageInstance> m_foliage;
	uint32_t m_version = 1, m_foliageVersion = 1, m_shadeVersion = 1;
};

// ------------------------------------------------------------------------------------------------ scene
struct Entity
{
	uint32_t id = 0;
	uint32_t parent = 0;   // 0 = top level
	std::string name;
	ActorType type = ActorType::Empty;
	Transform transform;
	json props = json::object();
	bool visible = true;
	std::shared_ptr<Terrain> terrain;   // ActorType::Terrain only
	json components = json::array();    // [{ "type": "Rotator", ... }] - see world/Gameplay.h
};

class Scene
{
public:
	Entity& Create( ActorType type, const std::string& name = "", uint32_t parent = 0 );
	bool Remove( uint32_t id );                        // children go with it
	Entity* Find( uint32_t id );
	const Entity* Find( uint32_t id ) const;
	Entity* FindByName( const std::string& name );
	std::vector<Entity>& Entities() { return m_entities; }
	const std::vector<Entity>& Entities() const { return m_entities; }
	std::vector<uint32_t> Children( uint32_t id ) const;   // 0 = top level, in order
	bool IsAncestor( uint32_t ancestor, uint32_t id ) const;
	bool SetParent( uint32_t id, uint32_t parent );       // keeps the world transform; refuses cycles
	void Clear();
	std::string UniqueName( const std::string& stem ) const;

	Matrix WorldMatrix( uint32_t id ) const;
	Vector3 WorldPosition( uint32_t id ) const;
	bool Visible( uint32_t id ) const;                    // itself and every parent

	// ground height under (x, z) from every terrain actor (highest wins); `found` false when none covers it
	float GroundAt( float x, float z, bool* found = nullptr ) const;
	uint32_t Pick( const Vector3& origin, const Vector3& dir, Vector3* hitPoint = nullptr ) const;
	bool RaycastTerrain( const Vector3& origin, const Vector3& dir, Vector3& hit, uint32_t* terrainId = nullptr ) const;
	Terrain* FirstTerrain( uint32_t* id = nullptr );

	json ToJson( const std::string& levelName = "" ) const;
	bool FromJson( const json& doc, std::string* error = nullptr );
	Scene Clone() const;

	json settings = DefaultWorldSettings();
	uint32_t nextId = 1;

private:
	std::vector<Entity> m_entities;
};

bool SaveLevel( const Scene& scene, const std::string& path, std::string* error = nullptr );
bool LoadLevel( Scene& scene, const std::string& path, std::string* error = nullptr );

// ------------------------------------------------------------------------------------------------ play
struct PlayInput
{
	bool forward = false, back = false, turnLeft = false, turnRight = false, strafeLeft = false, strafeRight = false;
	bool jump = false, run = false;
	bool turning = false;            // right mouse held: A / D strafe, mouse turns the character
	float mouseDX = 0.0f, mouseDY = 0.0f;
	bool orbit = false;              // left mouse drag: only the camera swings round
	float wheel = 0.0f;
	bool tabTarget = false;          // Tab: next hostile in front
	bool interact = false;           // F: talk to the quest giver in reach
	int ability = 0;                 // 1..4 pressed this frame
};

struct Creature
{
	uint32_t spawnId = 0;
	std::string name, kind;
	Vector3 position, home, target;
	float yaw = 0.0f, wait = 0.0f;
	bool hasTarget = false;
	enum State { Idle, Wander, Chase, Return, Dead } state = Idle;
	Vector3 color{ 0.7f, 0.27f, 0.18f };
	float speed = 2.5f, wander = 6.0f, aggro = 9.0f;
	bool hostile = true;
	int level = 1;
	float hp = 60, maxHp = 60, damage = 6, swing = 0, respawn = 0;
};

struct Ability
{
	const char* name;
	const char* icon;     // an icon-font glyph (UTF-8), drawn by the editor
	float cooldown, range, damage, remaining = 0;
};

struct Quest
{
	uint32_t giverId = 0;
	std::string name, target, text, done;
	int need = 0, have = 0, rewardXp = 0;
	enum State { Offered, Active, Ready, Complete } state = Offered;
};

struct FloatText
{
	Vector3 at;
	std::string text;
	float age = 0;
	bool good = false;
};

class PhysicsWorld;
class Behaviour;
struct Body;

class PlaySession
{
public:
	PlaySession( const Scene& level, bool possess, uint32_t seed = 1234567 );
	~PlaySession();
	static constexpr float kRadius = 0.4f, kHeight = 1.8f;   // the player's capsule
	void Tick( float dt, const PlayInput& in );

	Scene& World() { return m_world; }
	const Scene& World() const { return m_world; }
	bool Possessed() const { return m_possess; }
	Vector3 PlayerPosition() const { return m_pos; }
	float PlayerYaw() const { return m_yaw; }
	bool OnGround() const { return m_onGround; }
	std::vector<Creature>& Creatures() { return m_creatures; }
	const std::vector<Creature>& Creatures() const { return m_creatures; }
	void CameraEyeTarget( Vector3& eye, Vector3& target ) const;
	float Time() const { return m_time; }
	std::vector<std::string> TakeLog();
	void SetPlayerPosition( const Vector3& p ) { m_pos = p; }

	// the MMO layer (the HUD reads these)
	float hp = 100, maxHp = 100;
	int level = 1, xp = 0;
	int XpToLevel() const { return 100 + ( level - 1 ) * 60; }
	int target = -1;                                  // index into Creatures(), -1 = none
	std::vector<Ability> abilities;
	float gcd = 0;                                    // global cooldown
	std::vector<Quest> quests;
	int talkingTo = -1;                               // index into quests while the dialog is open
	std::string zone, zoneInfo;
	float zoneBanner = 0;                             // seconds left to show the zone name
	std::vector<FloatText> floats;
	float deadFor = 0;
	bool AcceptQuest( int index );
	bool CompleteQuest( int index );

	// for components (world/Gameplay.h)
	void Message( const std::string& text );   // the log + a message in the middle of the screen
	void Heal( float amount );
	void Damage( float amount );
	void AddXp( int amount );
	std::string toast;
	float toastFor = 0;
	const std::vector<Body>& Bodies() const;   // this tick's colliders

private:
	float Ground( float x, float z, float fallback ) const;
	void MovePlayer( float dt, const PlayInput& in );
	void MoveCreatures( float dt );
	void Combat( float dt, const PlayInput& in );
	void Zones();
	void Triggers();
	void GainXp( int amount );
	float Rand();

	Scene m_world;
	bool m_possess;
	std::mt19937 m_rng;
	Vector3 m_pos{ 0, 0, 0 }, m_spawn{ 0, 0, 0 };
	float m_yaw = 0.0f, m_vy = 0.0f, m_baseY = 0.0f, m_spawnYaw = 0.0f;
	bool m_onGround = true;
	float m_camYaw = 0.0f, m_camPitch = -0.35f, m_camDist = 7.0f;
	float m_speed = 7.0f, m_jump = 6.0f, m_gravity = 20.0f;
	float m_time = 0.0f;
	std::vector<Creature> m_creatures;
	std::vector<std::string> m_log;
	std::unique_ptr<PhysicsWorld> m_physics;
	std::vector<std::unique_ptr<Behaviour>> m_behaviours;
	std::vector<uint32_t> m_inside;   // triggers the player is in
};

// small helpers shared with the editor
Vector3 HexColor( const std::string& hex, const Vector3& fallback = Vector3( 1, 1, 1 ) );
std::string ToHex( const Vector3& c );
}
