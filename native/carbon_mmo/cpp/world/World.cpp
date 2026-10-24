// MODULE: world
#include "world/World.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <sstream>

namespace cmmo::world
{
namespace
{
constexpr float kPi = 3.14159265358979f;
constexpr float kDeg = kPi / 180.0f;

const std::vector<ActorInfo> kActors = {
	{ ActorType::Empty, "empty", "Empty Actor", "An empty transform: a group, a marker, a holder for logic." },
	{ ActorType::Mesh, "mesh", "Shape", "A primitive shape (cube, sphere, cylinder, cone, plane) for blocking out the world." },
	{ ActorType::PointLight, "pointLight", "Point Light", "Light from one point in every direction, fading with distance." },
	{ ActorType::DirLight, "dirLight", "Sun", "Directional light: parallel rays, like the sun. Rotate it to change the time of day." },
	{ ActorType::PlayerStart, "playerStart", "Player Start", "Where Play puts you (third person, WoW controls)." },
	{ ActorType::CreatureSpawn, "creatureSpawn", "Creature Spawn", "Creatures wander inside its ring; hostile ones attack when you come close and leash home." },
	{ ActorType::TriggerBox, "triggerBox", "Trigger Box", "An invisible box that reports when the player enters and leaves (quests, zones)." },
	{ ActorType::Terrain, "terrain", "Terrain", "Ground you sculpt and paint. Play walks on it." },
};

// -------------------------------------------------------------------------------------- base64
const char* kB64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
std::string Encode64( const uint8_t* data, size_t n )
{
	std::string out;
	out.reserve( ( n + 2 ) / 3 * 4 );
	for( size_t i = 0; i < n; i += 3 )
	{
		uint32_t v = uint32_t( data[i] ) << 16;
		if( i + 1 < n ) v |= uint32_t( data[i + 1] ) << 8;
		if( i + 2 < n ) v |= data[i + 2];
		out += kB64[( v >> 18 ) & 63];
		out += kB64[( v >> 12 ) & 63];
		out += i + 1 < n ? kB64[( v >> 6 ) & 63] : '=';
		out += i + 2 < n ? kB64[v & 63] : '=';
	}
	return out;
}
std::vector<uint8_t> Decode64( const std::string& s )
{
	int lut[256];
	std::fill( lut, lut + 256, -1 );
	for( int i = 0; i < 64; ++i ) lut[(unsigned char)kB64[i]] = i;
	std::vector<uint8_t> out;
	uint32_t v = 0;
	int bits = 0;
	for( unsigned char ch : s )
	{
		if( lut[ch] < 0 ) continue;
		v = ( v << 6 ) | uint32_t( lut[ch] );
		bits += 6;
		if( bits >= 8 )
		{
			bits -= 8;
			out.push_back( uint8_t( ( v >> bits ) & 0xFF ) );
		}
	}
	return out;
}

float Clamp( float v, float lo, float hi ) { return std::max( lo, std::min( hi, v ) ); }
float Num( const json& p, const char* key, float fallback )
{
	auto it = p.find( key );
	return it != p.end() && it->is_number() ? it->get<float>() : fallback;
}
}

// ------------------------------------------------------------------------------------------------ actors
const std::vector<ActorInfo>& Actors() { return kActors; }
const ActorInfo& InfoOf( ActorType type ) { return kActors[size_t( type )]; }
ActorType TypeFromId( const std::string& id )
{
	for( const auto& a : kActors )
		if( id == a.id ) return a.type;
	return ActorType::Empty;
}

json DefaultProps( ActorType type )
{
	switch( type )
	{
	case ActorType::Mesh: return { { "shape", "cube" }, { "color", "#b8b2a6" } };
	case ActorType::PointLight: return { { "color", "#ffd9a0" }, { "intensity", 2.0 }, { "range", 15.0 } };
	case ActorType::DirLight: return { { "color", "#fff4e0" }, { "intensity", 1.0 } };
	case ActorType::PlayerStart: return { { "speed", 7.0 }, { "jump", 6.0 }, { "camDist", 7.0 } };
	case ActorType::CreatureSpawn:
		return { { "creature", "Wolf" }, { "level", 1 }, { "hostile", true }, { "count", 3 }, { "wander", 6.0 },
				 { "speed", 2.5 }, { "aggro", 9.0 }, { "color", "#b5452f" } };
	case ActorType::TriggerBox: return { { "size", { 2.0, 2.0, 2.0 } } };
	case ActorType::Terrain: return { { "res", 64 }, { "size", 128.0 } };
	default: return json::object();
	}
}

Vector3 HexColor( const std::string& hex, const Vector3& fallback )
{
	std::string h = hex;
	if( !h.empty() && h[0] == '#' ) h = h.substr( 1 );
	if( h.size() != 6 ) return fallback;
	try
	{
		unsigned long v = std::stoul( h, nullptr, 16 );
		return Vector3( ( ( v >> 16 ) & 255 ) / 255.0f, ( ( v >> 8 ) & 255 ) / 255.0f, ( v & 255 ) / 255.0f );
	}
	catch( ... )
	{
		return fallback;
	}
}
std::string ToHex( const Vector3& c )
{
	char buf[8];
	auto b = []( float f ) { return int( Clamp( f, 0.0f, 1.0f ) * 255.0f + 0.5f ); };
	std::snprintf( buf, sizeof( buf ), "#%02x%02x%02x", b( c.x ), b( c.y ), b( c.z ) );
	return buf;
}

Matrix Transform::World() const
{
	// Carbon row vectors: scale, then rotate X, Y, Z, then translate
	return ScalingMatrix( scale ) * RotationXMatrix( rotation.x * kDeg ) * RotationYMatrix( rotation.y * kDeg ) *
		   RotationZMatrix( rotation.z * kDeg ) * TranslationMatrix( position );
}

// ------------------------------------------------------------------------------------------------ terrain
Terrain::Terrain( int res, float size )
	: m_res( std::max( 4, std::min( 256, res ) ) ), m_size( std::max( 8.0f, size ) )
{
	m_h.assign( size_t( VertexCount() ), 0.0f );
	m_c.resize( size_t( VertexCount() ) * 3 );
	for( int i = 0; i < VertexCount(); ++i )
	{
		m_c[i * 3] = 79;
		m_c[i * 3 + 1] = 122;
		m_c[i * 3 + 2] = 50;   // grass
	}
}

bool Terrain::Inside( float x, float z ) const
{
	const float half = m_size * 0.5f;
	return x >= -half && x <= half && z >= -half && z <= half;
}

float Terrain::HeightAt( float x, float z ) const
{
	if( !Inside( x, z ) ) return 0.0f;
	const float gx = ( x / m_size + 0.5f ) * m_res, gz = ( z / m_size + 0.5f ) * m_res;
	const int x0 = std::min( m_res - 1, int( gx ) ), z0 = std::min( m_res - 1, int( gz ) );
	const float fx = gx - x0, fz = gz - z0;
	const int n = m_res + 1;
	auto at = [&]( int i, int j ) { return m_h[size_t( j * n + i )]; };
	return ( at( x0, z0 ) * ( 1 - fx ) + at( x0 + 1, z0 ) * fx ) * ( 1 - fz ) +
		   ( at( x0, z0 + 1 ) * ( 1 - fx ) + at( x0 + 1, z0 + 1 ) * fx ) * fz;
}

Vector3 Terrain::NormalAt( float x, float z ) const
{
	const float e = m_size / m_res;
	const float hl = HeightAt( x - e, z ), hr = HeightAt( x + e, z ), hd = HeightAt( x, z - e ), hu = HeightAt( x, z + e );
	return Normalize( Vector3( hl - hr, 2.0f * e, hd - hu ) );
}

int Terrain::Sculpt( float x, float z, const Brush& brush )
{
	const int n = m_res + 1;
	const float cell = m_size / m_res;
	const float r = std::max( cell * 0.5f, brush.radius );
	auto toGrid = [&]( float v ) { return ( v / m_size + 0.5f ) * m_res; };
	const int i0 = std::max( 0, int( std::floor( toGrid( x - r ) ) ) ), i1 = std::min( m_res, int( std::ceil( toGrid( x + r ) ) ) );
	const int j0 = std::max( 0, int( std::floor( toGrid( z - r ) ) ) ), j1 = std::min( m_res, int( std::ceil( toGrid( z + r ) ) ) );
	const std::vector<float> old = brush.mode == Brush::Smooth ? m_h : std::vector<float>();
	int changed = 0;
	for( int j = j0; j <= j1; ++j )
		for( int i = i0; i <= i1; ++i )
		{
			const float vx = ( float( i ) / m_res - 0.5f ) * m_size, vz = ( float( j ) / m_res - 0.5f ) * m_size;
			const float d = std::hypot( vx - x, vz - z );
			if( d > r ) continue;
			const float f = 0.5f + 0.5f * std::cos( kPi * d / r );   // smooth falloff 1 -> 0
			const size_t k = size_t( j * n + i );
			switch( brush.mode )
			{
			case Brush::Raise: m_h[k] += brush.strength * f; break;
			case Brush::Lower: m_h[k] -= brush.strength * f; break;
			case Brush::Flatten: m_h[k] += ( brush.flattenHeight - m_h[k] ) * std::min( 1.0f, brush.strength * f ); break;
			case Brush::Smooth:
			{
				float s = 0;
				int m = 0;
				for( int dj = -1; dj <= 1; ++dj )
					for( int di = -1; di <= 1; ++di )
					{
						const int ii = i + di, jj = j + dj;
						if( ii < 0 || jj < 0 || ii > m_res || jj > m_res ) continue;
						s += old[size_t( jj * n + ii )];
						++m;
					}
				m_h[k] += ( s / m - m_h[k] ) * std::min( 1.0f, brush.strength * f );
				break;
			}
			case Brush::Paint:
			{
				const float w = std::min( 1.0f, brush.strength * f );
				const float target[3] = { brush.color.x * 255.0f, brush.color.y * 255.0f, brush.color.z * 255.0f };
				for( int q = 0; q < 3; ++q )
				{
					const float c = m_c[k * 3 + q];
					m_c[k * 3 + q] = uint8_t( Clamp( std::round( c + ( target[q] - c ) * w ), 0.0f, 255.0f ) );
				}
				break;
			}
			}
			++changed;
		}
	if( changed ) ++m_version;
	return changed;
}

bool Terrain::Raycast( const Vector3& origin, const Vector3& dir, float maxDist, Vector3& hit ) const
{
	// march until below the surface, then bisect
	const float step = std::max( 0.05f, m_size / m_res * 0.25f );
	Vector3 prev = origin;
	bool prevAbove = prev.y >= HeightAt( prev.x, prev.z ) || !Inside( prev.x, prev.z );
	for( float t = step; t <= maxDist; t += step )
	{
		const Vector3 p = origin + dir * t;
		if( !Inside( p.x, p.z ) )
		{
			prev = p;
			prevAbove = true;
			continue;
		}
		const bool above = p.y >= HeightAt( p.x, p.z );
		if( prevAbove && !above )
		{
			float a = t - step, b = t;
			for( int k = 0; k < 24; ++k )
			{
				const float mid = 0.5f * ( a + b );
				const Vector3 q = origin + dir * mid;
				if( q.y >= HeightAt( q.x, q.z ) ) a = mid; else b = mid;
			}
			hit = origin + dir * ( 0.5f * ( a + b ) );
			return true;
		}
		prev = p;
		prevAbove = above;
	}
	return false;
}

std::string Terrain::HeightsBase64() const { return Encode64( reinterpret_cast<const uint8_t*>( m_h.data() ), m_h.size() * sizeof( float ) ); }
std::string Terrain::ColorsBase64() const { return Encode64( m_c.data(), m_c.size() ); }

bool Terrain::Load( int res, float size, const std::string& heights64, const std::string& colors64 )
{
	Terrain fresh( res, size );
	const auto h = Decode64( heights64 );
	if( !heights64.empty() )
	{
		if( h.size() != fresh.m_h.size() * sizeof( float ) ) return false;
		std::memcpy( fresh.m_h.data(), h.data(), h.size() );
	}
	const auto c = Decode64( colors64 );
	if( !colors64.empty() )
	{
		if( c.size() != fresh.m_c.size() ) return false;
		fresh.m_c = c;
	}
	fresh.m_version = m_version + 1;
	*this = std::move( fresh );
	return true;
}

// ------------------------------------------------------------------------------------------------ scene
std::string Scene::UniqueName( const std::string& stem ) const
{
	int hi = 0;
	bool bare = false;
	for( const auto& e : m_entities )
	{
		if( e.name == stem ) bare = true;
		if( e.name.size() > stem.size() && e.name.compare( 0, stem.size(), stem ) == 0 )
		{
			const std::string tail = e.name.substr( stem.size() );
			if( tail.find_first_not_of( "0123456789" ) == std::string::npos ) hi = std::max( hi, std::stoi( tail ) );
		}
	}
	return ( !bare && hi == 0 ) ? stem + "1" : stem + std::to_string( hi + 1 );
}

Entity& Scene::Create( ActorType type, const std::string& name )
{
	Entity e;
	e.id = nextId++;
	e.type = type;
	std::string stem = InfoOf( type ).label;
	stem.erase( std::remove( stem.begin(), stem.end(), ' ' ), stem.end() );
	e.name = name.empty() ? UniqueName( stem ) : name;
	e.props = DefaultProps( type );
	if( type == ActorType::Terrain ) e.terrain = std::make_shared<Terrain>( e.props["res"].get<int>(), e.props["size"].get<float>() );
	m_entities.push_back( std::move( e ) );
	return m_entities.back();
}

bool Scene::Remove( uint32_t id )
{
	auto it = std::find_if( m_entities.begin(), m_entities.end(), [id]( const Entity& e ) { return e.id == id; } );
	if( it == m_entities.end() ) return false;
	m_entities.erase( it );
	return true;
}

Entity* Scene::Find( uint32_t id )
{
	for( auto& e : m_entities )
		if( e.id == id ) return &e;
	return nullptr;
}
const Entity* Scene::Find( uint32_t id ) const { return const_cast<Scene*>( this )->Find( id ); }
Entity* Scene::FindByName( const std::string& name )
{
	for( auto& e : m_entities )
		if( e.name == name ) return &e;
	return nullptr;
}
void Scene::Clear()
{
	m_entities.clear();
	nextId = 1;
}

float Scene::GroundAt( float x, float z, bool* found ) const
{
	bool any = false;
	float best = 0.0f;
	for( const auto& e : m_entities )
	{
		if( e.type != ActorType::Terrain || !e.terrain || !e.visible ) continue;
		const float lx = x - e.transform.position.x, lz = z - e.transform.position.z;
		if( !e.terrain->Inside( lx, lz ) ) continue;
		const float h = e.terrain->HeightAt( lx, lz ) + e.transform.position.y;
		if( !any || h > best ) best = h;
		any = true;
	}
	if( found ) *found = any;
	return best;
}

bool Scene::RaycastTerrain( const Vector3& origin, const Vector3& dir, Vector3& hit, uint32_t* terrainId ) const
{
	float bestT = 1e30f;
	bool any = false;
	for( const auto& e : m_entities )
	{
		if( e.type != ActorType::Terrain || !e.terrain || !e.visible ) continue;
		Vector3 h;
		if( e.terrain->Raycast( origin - e.transform.position, dir, 4000.0f, h ) )
		{
			const Vector3 w = h + e.transform.position;
			const float t = Length( w - origin );
			if( t < bestT )
			{
				bestT = t;
				hit = w;
				any = true;
				if( terrainId ) *terrainId = e.id;
			}
		}
	}
	return any;
}

uint32_t Scene::Pick( const Vector3& origin, const Vector3& dir, Vector3* hitPoint ) const
{
	// actors: ray vs a sphere around each (good enough for picking markers and shapes); terrain: the surface
	uint32_t best = 0;
	float bestT = 1e30f;
	for( const auto& e : m_entities )
	{
		if( !e.visible || e.type == ActorType::Terrain ) continue;
		const Vector3& s = e.transform.scale;
		float radius = 0.8f * std::max( std::fabs( s.x ), std::max( std::fabs( s.y ), std::fabs( s.z ) ) );
		Vector3 c = e.transform.position;
		if( e.type == ActorType::PlayerStart ) { c.y += 0.9f; radius = 1.0f; }
		if( e.type == ActorType::CreatureSpawn ) { c.y += 1.0f; radius = 1.0f; }
		if( e.type == ActorType::PointLight || e.type == ActorType::DirLight || e.type == ActorType::Empty ) radius = 0.6f;
		const Vector3 oc = origin - c;
		const float b = Dot( oc, dir ), cc = Dot( oc, oc ) - radius * radius, disc = b * b - cc;
		if( disc < 0 ) continue;
		const float t = -b - std::sqrt( disc );
		if( t > 0 && t < bestT )
		{
			bestT = t;
			best = e.id;
		}
	}
	Vector3 th;
	uint32_t tid = 0;
	if( RaycastTerrain( origin, dir, th, &tid ) && Length( th - origin ) < bestT )
	{
		if( hitPoint ) *hitPoint = th;
		return tid;
	}
	if( best && hitPoint ) *hitPoint = origin + dir * bestT;
	return best;
}

json Scene::ToJson( const std::string& levelName ) const
{
	json actors = json::array();
	for( const auto& e : m_entities )
	{
		json a = {
			{ "id", e.id }, { "name", e.name }, { "type", InfoOf( e.type ).id }, { "visible", e.visible }, { "props", e.props },
			{ "position", { e.transform.position.x, e.transform.position.y, e.transform.position.z } },
			{ "rotation", { e.transform.rotation.x, e.transform.rotation.y, e.transform.rotation.z } },
			{ "scale", { e.transform.scale.x, e.transform.scale.y, e.transform.scale.z } },
		};
		if( e.terrain )
		{
			a["terrain"] = { { "res", e.terrain->Res() }, { "size", e.terrain->Size() },
							 { "heights", e.terrain->HeightsBase64() }, { "colors", e.terrain->ColorsBase64() } };
		}
		actors.push_back( std::move( a ) );
	}
	return { { "format", "cmmo-level" }, { "version", 1 }, { "name", levelName }, { "nextId", nextId }, { "actors", actors } };
}

bool Scene::FromJson( const json& doc, std::string* error )
{
	auto fail = [&]( const std::string& why ) { if( error ) *error = why; return false; };
	if( !doc.is_object() || doc.value( "format", "" ) != "cmmo-level" ) return fail( "not a Carbon MMO level" );
	if( doc.value( "version", 0 ) > 1 ) return fail( "level made by a newer editor" );
	Scene fresh;
	try
	{
		for( const auto& a : doc.at( "actors" ) )
		{
			Entity e;
			e.id = a.at( "id" ).get<uint32_t>();
			e.name = a.value( "name", "" );
			e.type = TypeFromId( a.value( "type", "empty" ) );
			e.visible = a.value( "visible", true );
			e.props = DefaultProps( e.type );
			if( a.contains( "props" ) && a["props"].is_object() ) e.props.update( a["props"] );
			auto v3 = [&]( const char* k, Vector3 d ) {
				if( !a.contains( k ) ) return d;
				const auto& v = a[k];
				return Vector3( v.at( 0 ).get<float>(), v.at( 1 ).get<float>(), v.at( 2 ).get<float>() );
			};
			e.transform.position = v3( "position", Vector3( 0, 0, 0 ) );
			e.transform.rotation = v3( "rotation", Vector3( 0, 0, 0 ) );
			e.transform.scale = v3( "scale", Vector3( 1, 1, 1 ) );
			if( e.type == ActorType::Terrain )
			{
				const json t = a.value( "terrain", json::object() );
				e.terrain = std::make_shared<Terrain>( t.value( "res", 64 ), t.value( "size", 128.0f ) );
				if( !e.terrain->Load( t.value( "res", 64 ), t.value( "size", 128.0f ), t.value( "heights", "" ), t.value( "colors", "" ) ) )
					return fail( "terrain data of " + e.name + " is damaged" );
			}
			fresh.nextId = std::max( fresh.nextId, e.id + 1 );
			fresh.m_entities.push_back( std::move( e ) );
		}
		fresh.nextId = std::max( fresh.nextId, doc.value( "nextId", 1u ) );
	}
	catch( const std::exception& ex )
	{
		return fail( std::string( "bad level file: " ) + ex.what() );
	}
	*this = std::move( fresh );
	return true;
}

Scene Scene::Clone() const
{
	Scene out = *this;
	for( auto& e : out.m_entities )
		if( e.terrain ) e.terrain = std::make_shared<Terrain>( *e.terrain );
	return out;
}

bool SaveLevel( const Scene& scene, const std::string& path, std::string* error )
{
	std::ofstream f( path, std::ios::binary );
	if( !f )
	{
		if( error ) *error = "cannot write " + path;
		return false;
	}
	std::string stem = path.substr( path.find_last_of( "/\\" ) + 1 );
	f << scene.ToJson( stem ).dump( 1 );
	return bool( f );
}

bool LoadLevel( Scene& scene, const std::string& path, std::string* error )
{
	std::ifstream f( path, std::ios::binary );
	if( !f )
	{
		if( error ) *error = "cannot open " + path;
		return false;
	}
	json doc = json::parse( f, nullptr, false );
	if( doc.is_discarded() )
	{
		if( error ) *error = "not JSON: " + path;
		return false;
	}
	return scene.FromJson( doc, error );
}

// ------------------------------------------------------------------------------------------------ play
PlaySession::PlaySession( const Scene& level, bool possess, uint32_t seed )
	: m_world( level.Clone() ), m_possess( possess ), m_rng( seed )
{
	for( const auto& e : m_world.Entities() )
	{
		if( e.type == ActorType::PlayerStart && e.visible )
		{
			m_pos = e.transform.position;
			m_yaw = e.transform.rotation.y * kDeg;
			m_speed = Num( e.props, "speed", 7.0f );
			m_jump = Num( e.props, "jump", 6.0f );
			m_camDist = Num( e.props, "camDist", 7.0f );
			break;
		}
	}
	m_baseY = m_pos.y;
	bool found = false;
	const float g = m_world.GroundAt( m_pos.x, m_pos.z, &found );
	if( found && g > m_pos.y ) m_pos.y = g;
	m_camYaw = m_yaw;

	for( const auto& e : m_world.Entities() )
	{
		if( e.type != ActorType::CreatureSpawn || !e.visible ) continue;
		const int count = std::max( 0, std::min( 50, e.props.value( "count", 3 ) ) );
		for( int i = 0; i < count; ++i )
		{
			Creature c;
			c.spawnId = e.id;
			c.name = e.props.value( "creature", std::string( "Creature" ) ) + ( count > 1 ? " " + std::to_string( i + 1 ) : "" );
			c.home = e.transform.position;
			c.wander = Num( e.props, "wander", 6.0f );
			c.speed = Num( e.props, "speed", 2.5f );
			c.aggro = Num( e.props, "aggro", 9.0f );
			c.hostile = e.props.value( "hostile", true );
			c.color = HexColor( e.props.value( "color", std::string( "#b5452f" ) ) );
			const float a = Rand() * 2 * kPi, r = std::sqrt( Rand() ) * c.wander;
			c.position = Vector3( c.home.x + std::cos( a ) * r, 0, c.home.z + std::sin( a ) * r );
			c.position.y = Ground( c.position.x, c.position.z, c.home.y );
			c.wait = Rand() * 2;
			m_creatures.push_back( c );
		}
	}
}

float PlaySession::Rand() { return std::uniform_real_distribution<float>( 0.0f, 1.0f )( m_rng ); }

float PlaySession::Ground( float x, float z, float fallback ) const
{
	bool found = false;
	const float g = m_world.GroundAt( x, z, &found );
	return found ? g : fallback;
}

void PlaySession::Tick( float dt, const PlayInput& in )
{
	dt = Clamp( dt, 0.0f, 0.1f );   // a stall must not teleport anything
	m_time += dt;
	if( m_possess ) MovePlayer( dt, in );
	MoveCreatures( dt );
}

void PlaySession::MovePlayer( float dt, const PlayInput& in )
{
	// mouse: right drag turns you with the camera, left drag orbits only the camera, wheel zooms (WoW)
	if( in.turning || in.orbit )
	{
		m_camYaw -= in.mouseDX * 0.005f;
		m_camPitch = Clamp( m_camPitch - in.mouseDY * 0.005f, -1.35f, 0.6f );
		if( in.turning ) m_yaw = m_camYaw;
	}
	if( in.wheel != 0.0f ) m_camDist = Clamp( m_camDist * ( in.wheel > 0 ? 1.12f : 1.0f / 1.12f ), 1.5f, 40.0f );
	// keys: A / D turn (strafe while turning with the mouse), Q / E strafe, W / S forward / back (back slower)
	if( !in.turning )
	{
		if( in.turnLeft ) { m_yaw += 2.6f * dt; m_camYaw += 2.6f * dt; }
		if( in.turnRight ) { m_yaw -= 2.6f * dt; m_camYaw -= 2.6f * dt; }
	}
	const Vector3 fwd( -std::sin( m_yaw ), 0, -std::cos( m_yaw ) ), right( std::cos( m_yaw ), 0, -std::sin( m_yaw ) );
	Vector3 mv( 0, 0, 0 );
	if( in.forward ) mv += fwd;
	if( in.back ) mv -= fwd * 0.65f;
	if( in.strafeRight || ( in.turning && in.turnRight ) ) mv += right;
	if( in.strafeLeft || ( in.turning && in.turnLeft ) ) mv -= right;
	if( LengthSq( mv ) > 1.0f ) mv = Normalize( mv );
	m_pos += mv * ( m_speed * ( in.run ? 1.6f : 1.0f ) * dt );
	// gravity, jumping, feet on the terrain (or the Player Start's height where there is none)
	const float ground = Ground( m_pos.x, m_pos.z, m_baseY );
	if( in.jump && m_onGround )
	{
		m_vy = m_jump;
		m_onGround = false;
	}
	m_vy -= 20.0f * dt;
	m_pos.y += m_vy * dt;
	if( m_pos.y <= ground )
	{
		m_pos.y = ground;
		m_vy = 0;
		m_onGround = true;
	}
}

void PlaySession::MoveCreatures( float dt )
{
	for( auto& c : m_creatures )
	{
		const float toPlayer = m_possess ? Length( m_pos - c.position ) : 1e9f;
		const float fromHome = Length( c.position - c.home );
		const bool chasing = c.state == Creature::Chase;
		if( c.hostile && m_possess && ( chasing ? toPlayer < c.aggro * 2.5f && fromHome < c.wander + 30.0f : toPlayer < c.aggro ) )
		{
			if( !chasing ) m_log.push_back( c.name + " attacks!" );
			c.state = Creature::Chase;
			c.hasTarget = toPlayer > 1.6f;
			c.target = m_pos;
		}
		else if( chasing )
		{
			c.state = Creature::Return;   // leashed: back home (WoW evade)
			c.target = c.home;
			c.hasTarget = true;
		}
		else if( !c.hasTarget )
		{
			c.wait -= dt;
			if( c.wait <= 0 )
			{
				const float a = Rand() * 2 * kPi, r = std::sqrt( Rand() ) * c.wander;
				c.target = Vector3( c.home.x + std::cos( a ) * r, 0, c.home.z + std::sin( a ) * r );
				c.hasTarget = true;
				c.wait = 2 + Rand() * 3;
				c.state = Creature::Wander;
			}
		}
		if( c.hasTarget )
		{
			Vector3 d( c.target.x - c.position.x, 0, c.target.z - c.position.z );
			const float len = Length( d );
			const float speed = c.speed * ( c.state == Creature::Chase ? 2.2f : c.state == Creature::Return ? 3.0f : 1.0f );
			if( len < 0.15f )
			{
				c.hasTarget = false;
				if( c.state == Creature::Return ) c.state = Creature::Idle;
			}
			else
			{
				c.position += d * ( std::min( len, speed * dt ) / len );
				c.yaw = std::atan2( -d.x, -d.z );
			}
		}
		c.position.y = Ground( c.position.x, c.position.z, c.home.y );
	}
}

void PlaySession::CameraEyeTarget( Vector3& eye, Vector3& target ) const
{
	target = m_pos + Vector3( 0, 1.6f, 0 );
	const float cp = std::cos( m_camPitch );
	eye = target + Vector3( std::sin( m_camYaw ) * cp, -std::sin( m_camPitch ), std::cos( m_camYaw ) * cp ) * m_camDist;
	const float g = Ground( eye.x, eye.z, -1e9f );
	if( eye.y < g + 0.4f ) eye.y = g + 0.4f;   // never under the ground
}

std::vector<std::string> PlaySession::TakeLog()
{
	std::vector<std::string> out;
	out.swap( m_log );
	return out;
}
}
