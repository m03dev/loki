// MODULE: world
// The engine's world model - everything the editor edits and Play simulates, with no graphics and no UI.
// All vectors and matrices are Carbon math (carbonengine/math): Vector3, Matrix.
//
//   Scene        entities (actors) with a transform, a type and a JSON property bag; terrain data per terrain actor
//   Terrain      height grid + vertex colours: sculpt (raise / lower / smooth / flatten), paint, height lookup, ray hit
//   PlaySession  Play in Editor on a COPY of the scene (Stop = drop the copy, so the level is always restored):
//                third-person player with WoW controls, creatures that wander / aggro / leash
//   Level files  Scene <-> JSON ("cmmo-level" v1), terrain arrays as base64
//
// Swap points: replace PlaySession with the networked server simulation (python/cmmo) - the editor only talks to
// the PlaySession interface below.
#pragma once

#include <cstdint>
#include <map>
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
	Mesh,          // a primitive shape (cube, sphere, cylinder, cone, plane) - level blockout
	PointLight,
	DirLight,
	PlayerStart,
	CreatureSpawn,
	TriggerBox,
	Terrain,
	Count
};

struct ActorInfo
{
	ActorType type;
	const char* id;       // stable name in level files
	const char* label;    // shown in the editor
	const char* what;     // tooltip
};
const std::vector<ActorInfo>& Actors();
const ActorInfo& InfoOf( ActorType type );
ActorType TypeFromId( const std::string& id );
json DefaultProps( ActorType type );

struct Transform
{
	Vector3 position{ 0.0f, 0.0f, 0.0f };
	Vector3 rotation{ 0.0f, 0.0f, 0.0f };   // degrees, applied X then Y then Z
	Vector3 scale{ 1.0f, 1.0f, 1.0f };
	Matrix World() const;                    // Carbon row-vector convention: v * World
};

// ------------------------------------------------------------------------------------------------ terrain
struct Brush
{
	enum Mode { Raise, Lower, Smooth, Flatten, Paint } mode = Raise;
	float radius = 6.0f;
	float strength = 0.4f;
	Vector3 color{ 0.48f, 0.35f, 0.23f };     // paint colour (0..1)
	float flattenHeight = 0.0f;
};

class Terrain
{
public:
	Terrain( int res = 64, float size = 128.0f );
	int Res() const { return m_res; }
	float Size() const { return m_size; }
	int VertexCount() const { return ( m_res + 1 ) * ( m_res + 1 ); }
	const std::vector<float>& Heights() const { return m_h; }
	const std::vector<uint8_t>& Colors() const { return m_c; }
	uint32_t Version() const { return m_version; }   // bumps on every change (the renderer re-uploads)

	// local coordinates: the grid is centred on (0, 0), x / z in [-size/2, size/2]
	bool Inside( float x, float z ) const;
	float HeightAt( float x, float z ) const;          // bilinear; 0 outside
	Vector3 NormalAt( float x, float z ) const;
	int Sculpt( float x, float z, const Brush& brush );   // returns vertices changed
	bool Raycast( const Vector3& origin, const Vector3& dir, float maxDist, Vector3& hit ) const;

	std::string HeightsBase64() const;
	std::string ColorsBase64() const;
	bool Load( int res, float size, const std::string& heights64, const std::string& colors64 );

private:
	int m_res;
	float m_size;
	std::vector<float> m_h;
	std::vector<uint8_t> m_c;
	uint32_t m_version = 1;
};

// ------------------------------------------------------------------------------------------------ scene
struct Entity
{
	uint32_t id = 0;
	std::string name;
	ActorType type = ActorType::Empty;
	Transform transform;
	json props = json::object();
	bool visible = true;
	std::shared_ptr<Terrain> terrain;   // ActorType::Terrain only
};

class Scene
{
public:
	Entity& Create( ActorType type, const std::string& name = "" );
	bool Remove( uint32_t id );
	Entity* Find( uint32_t id );
	const Entity* Find( uint32_t id ) const;
	Entity* FindByName( const std::string& name );
	std::vector<Entity>& Entities() { return m_entities; }
	const std::vector<Entity>& Entities() const { return m_entities; }
	void Clear();
	std::string UniqueName( const std::string& stem ) const;

	// ground height under (x, z) from every terrain actor (highest wins); `found` false when none covers it
	float GroundAt( float x, float z, bool* found = nullptr ) const;
	// pick: the nearest entity hit by a world ray (terrain included). 0 = nothing.
	uint32_t Pick( const Vector3& origin, const Vector3& dir, Vector3* hitPoint = nullptr ) const;
	// nearest terrain hit (for the brush)
	bool RaycastTerrain( const Vector3& origin, const Vector3& dir, Vector3& hit, uint32_t* terrainId = nullptr ) const;

	json ToJson( const std::string& levelName = "" ) const;
	bool FromJson( const json& doc, std::string* error = nullptr );
	Scene Clone() const;   // deep copy (terrain data included)

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
};

struct Creature
{
	uint32_t spawnId = 0;
	std::string name;
	Vector3 position, home, target;
	float yaw = 0.0f, wait = 0.0f;
	bool hasTarget = false;
	enum State { Idle, Wander, Chase, Return } state = Idle;
	Vector3 color{ 0.7f, 0.27f, 0.18f };
	float speed = 2.5f, wander = 6.0f, aggro = 9.0f;
	bool hostile = true;
};

class PlaySession
{
public:
	PlaySession( const Scene& level, bool possess, uint32_t seed = 1234567 );
	void Tick( float dt, const PlayInput& in );

	Scene& World() { return m_world; }                 // the copy being played
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

private:
	float Ground( float x, float z, float fallback ) const;
	void MovePlayer( float dt, const PlayInput& in );
	void MoveCreatures( float dt );
	float Rand();

	Scene m_world;
	bool m_possess;
	std::mt19937 m_rng;
	Vector3 m_pos{ 0, 0, 0 };
	float m_yaw = 0.0f, m_vy = 0.0f, m_baseY = 0.0f;
	bool m_onGround = true;
	float m_camYaw = 0.0f, m_camPitch = -0.35f, m_camDist = 7.0f;
	float m_speed = 5.0f, m_jump = 6.0f;
	float m_time = 0.0f;
	std::vector<Creature> m_creatures;
	std::vector<std::string> m_log;
};

// small helpers shared with the editor
Vector3 HexColor( const std::string& hex, const Vector3& fallback = Vector3( 1, 1, 1 ) );
std::string ToHex( const Vector3& c );
}
