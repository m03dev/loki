// MODULE: world
#include "world/World.h"

#include "world/Gameplay.h"
#include "world/Physics.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <fstream>

namespace cmmo::world
{
namespace
{
constexpr float kPi = 3.14159265358979f;
constexpr float kDeg = kPi / 180.0f;

const std::vector<ActorInfo> kActors = {
	{ ActorType::Empty, "empty", "Empty", "An empty node: a group or a marker. Parent other actors to it.", "Basic" },
	{ ActorType::Mesh, "mesh", "Shape", "A primitive (cube, sphere, cylinder, cone, plane) for blocking out buildings and props.", "Basic" },
	{ ActorType::PointLight, "pointLight", "Point Light", "Light from one point, fading with distance: torches, lamps, campfires.", "Lighting" },
	{ ActorType::DirLight, "dirLight", "Sun", "Directional light. Rotate it to change the time of day.", "Lighting" },
	{ ActorType::PlayerStart, "playerStart", "Player Start", "Where players enter the world (third person, WoW controls).", "Gameplay" },
	{ ActorType::CreatureSpawn, "creatureSpawn", "Creature Spawn", "Spawns creatures that wander, fight back, drop XP and respawn.", "Gameplay" },
	{ ActorType::TriggerBox, "triggerBox", "Trigger Box", "An invisible box that reports when players enter and leave.", "Gameplay" },
	{ ActorType::Terrain, "terrain", "Terrain", "Ground you sculpt, texture and cover with foliage (Terrain panel).", "World" },
	{ ActorType::QuestGiver, "questGiver", "Quest Giver", "An NPC with a kill quest. Players press F to talk.", "Gameplay" },
	{ ActorType::Zone, "zone", "Zone", "A named area: its name shows when players enter; level range and PvP.", "World" },
	{ ActorType::Model, "model", "Model", "A 3D model from the Content Browser (.glb / .gltf).", "Basic" },
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
std::string Str( const json& p, const char* key, const std::string& fallback )
{
	auto it = p.find( key );
	return it != p.end() && it->is_string() ? it->get<std::string>() : fallback;
}

// value noise (hash lattice) for terrain generation and the noise brush
float Hash( int x, int z, uint32_t seed )
{
	uint32_t h = uint32_t( x ) * 374761393u + uint32_t( z ) * 668265263u + seed * 2246822519u;
	h = ( h ^ ( h >> 13 ) ) * 1274126177u;
	return float( ( h ^ ( h >> 16 ) ) & 0xFFFFFF ) / float( 0xFFFFFF );
}
float ValueNoise( float x, float z, uint32_t seed )
{
	const int xi = int( std::floor( x ) ), zi = int( std::floor( z ) );
	const float fx = x - xi, fz = z - zi;
	const float ux = fx * fx * ( 3 - 2 * fx ), uz = fz * fz * ( 3 - 2 * fz );
	const float a = Hash( xi, zi, seed ), b = Hash( xi + 1, zi, seed ), c = Hash( xi, zi + 1, seed ), d = Hash( xi + 1, zi + 1, seed );
	return ( a + ( b - a ) * ux ) + ( ( c + ( d - c ) * ux ) - ( a + ( b - a ) * ux ) ) * uz;
}
float Fbm( float x, float z, uint32_t seed, int octaves )
{
	float sum = 0, amp = 1, norm = 0, f = 1;
	for( int o = 0; o < octaves; ++o )
	{
		sum += ( ValueNoise( x * f, z * f, seed + uint32_t( o ) * 101u ) * 2 - 1 ) * amp;
		norm += amp;
		amp *= 0.5f;
		f *= 2.03f;
	}
	return sum / norm;
}

// world matrix -> local transform (inverse of S * Rx * Ry * Rz * T, Carbon row vectors)
Transform Decompose( const Matrix& m )
{
	Transform t;
	t.position = Vector3( m._41, m._42, m._43 );
	const Vector3 r0( m._11, m._12, m._13 ), r1( m._21, m._22, m._23 ), r2( m._31, m._32, m._33 );
	t.scale = Vector3( Length( r0 ), Length( r1 ), Length( r2 ) );
	const Vector3 n0 = r0 / std::max( 1e-6f, t.scale.x ), n1 = r1 / std::max( 1e-6f, t.scale.y ), n2 = r2 / std::max( 1e-6f, t.scale.z );
	const float b = std::asin( Clamp( -n0.z, -1.0f, 1.0f ) );
	float a, c;
	if( std::fabs( std::cos( b ) ) > 1e-4f )
	{
		a = std::atan2( n1.z, n2.z );
		c = std::atan2( n0.y, n0.x );
	}
	else
	{
		c = 0;
		a = std::atan2( -n2.y, n1.y );
	}
	t.rotation = Vector3( a / kDeg, b / kDeg, c / kDeg );
	return t;
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
const char* FoliageName( FoliageKind k )
{
	static const char* n[] = { "Tree", "Pine", "Bush", "Rock", "Grass" };
	return n[size_t( k ) % size_t( FoliageKind::Count )];
}

json DefaultProps( ActorType type )
{
	switch( type )
	{
	case ActorType::Mesh: return { { "shape", "cube" }, { "color", "#b8b2a6" }, { "collision", true } };
	case ActorType::PointLight: return { { "color", "#ffb760" }, { "intensity", 2.0 }, { "range", 15.0 } };
	case ActorType::DirLight: return { { "color", "#fff1dc" }, { "intensity", 1.0 } };
	case ActorType::PlayerStart: return { { "speed", 7.0 }, { "jump", 6.0 }, { "camDist", 7.0 } };
	case ActorType::CreatureSpawn:
		return { { "creature", "Wolf" }, { "level", 2 }, { "hostile", true }, { "count", 3 }, { "wander", 6.0 }, { "speed", 2.5 },
				 { "aggro", 9.0 }, { "health", 70 }, { "damage", 6.0 }, { "respawn", 15.0 }, { "color", "#8c6d52" } };
	case ActorType::TriggerBox: return { { "size", { 2.0, 2.0, 2.0 } } };
	case ActorType::Terrain: return json::object();
	case ActorType::QuestGiver:
		return { { "npc", "Marshal Grey" }, { "quest", "Wolves at the Gate" }, { "target", "Wolf" }, { "count", 3 }, { "rewardXp", 150 },
				 { "text", "Wolves have been prowling the road. Thin their numbers and I'll see you rewarded." },
				 { "done", "Well fought. The road is safer for it." }, { "color", "#e8c547" } };
	case ActorType::Zone: return { { "zone", "Greenhollow Vale" }, { "levelMin", 1 }, { "levelMax", 5 }, { "pvp", false }, { "size", { 60.0, 40.0, 60.0 } } };
	case ActorType::Model: return { { "path", "" }, { "color", "#ffffff" } };
	default: return json::object();
	}
}

json DefaultWorldSettings()
{
	return { { "sky", "#7aa5d4" }, { "horizon", "#c9d9e6" }, { "ambient", "#56606e" }, { "fog", 0.0035 }, { "gravity", 20.0 }, { "name", "New World" } };
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

Matrix Transform::Local() const
{
	return ScalingMatrix( scale ) * RotationXMatrix( rotation.x * kDeg ) * RotationYMatrix( rotation.y * kDeg ) *
		   RotationZMatrix( rotation.z * kDeg ) * TranslationMatrix( position );
}

// ------------------------------------------------------------------------------------------------ terrain
Terrain::Terrain( int res, float size )
	: m_res( std::max( 8, std::min( 512, res ) ) ), m_size( std::max( 16.0f, size ) )
{
	m_h.assign( size_t( VertexCount() ), 0.0f );
	m_w.assign( size_t( VertexCount() ) * 4, 0 );
	for( int i = 0; i < VertexCount(); ++i ) m_w[size_t( i ) * 4] = 255;
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

Vector3 Terrain::ColorAt( int i, int j ) const
{
	const size_t k = size_t( j * ( m_res + 1 ) + i );
	Vector3 c( 0, 0, 0 );
	for( int l = 0; l < kLayers; ++l ) c += layers[l].color * ( m_w[k * 4 + size_t( l )] / 255.0f );
	if( !autoShader ) return c;
	// auto-shader: where the grass layer is still showing, rock on steep ground and snow up high take over
	const float base = m_w[k * 4] / 255.0f;
	const float x = ( float( i ) / m_res - 0.5f ) * m_size, z = ( float( j ) / m_res - 0.5f ) * m_size;
	const float slope = std::acos( Clamp( NormalAt( x, z ).y, -1.0f, 1.0f ) ) / kDeg;
	const float rock = Clamp( ( slope - slopeDeg + 6.0f ) / 12.0f, 0.0f, 1.0f ) * base;
	const float snow = Clamp( ( m_h[k] - snowHeight + 3.0f ) / 6.0f, 0.0f, 1.0f ) * base * ( 1.0f - rock * 0.7f );
	c = c + ( layers[2].color - layers[0].color ) * rock;
	c = c + ( layers[3].color - c ) * snow;
	return c;
}

float Terrain::Falloff( float d, float r, Brush::Falloff f ) const
{
	const float t = Clamp( d / r, 0.0f, 1.0f );
	switch( f )
	{
	case Brush::Linear: return 1.0f - t;
	case Brush::Constant: return 1.0f;
	case Brush::Sharp: return ( 1.0f - t ) * ( 1.0f - t );
	default: return 0.5f + 0.5f * std::cos( kPi * t );
	}
}

int Terrain::Sculpt( float x, float z, const Brush& brush )
{
	const float cell = m_size / m_res;
	const float r = std::max( cell * 0.5f, brush.radius );
	if( brush.mode == Brush::Foliage || brush.mode == Brush::EraseFoliage )
	{
		if( brush.mode == Brush::EraseFoliage )
		{
			const size_t before = m_foliage.size();
			m_foliage.erase( std::remove_if( m_foliage.begin(), m_foliage.end(),
											 [&]( const FoliageInstance& f ) {
												 return ( f.kind == brush.foliage || brush.strength > 1.0f ) && std::hypot( f.x - x, f.z - z ) < r;
											 } ),
							 m_foliage.end() );
			const int removed = int( before - m_foliage.size() );
			if( removed ) ++m_foliageVersion;
			return removed;
		}
		std::mt19937 rng( brush.seed * 7919u + uint32_t( m_foliage.size() ) );
		std::uniform_real_distribution<float> u( 0, 1 );
		const int want = std::max( 1, int( brush.density * kPi * r * r / 20.0f ) );
		int added = 0;
		const float minGap = brush.foliage == FoliageKind::Grass ? 0.6f : brush.foliage == FoliageKind::Bush ? 1.5f : 3.0f;
		for( int i = 0; i < want * 3 && added < want; ++i )
		{
			const float a = u( rng ) * 2 * kPi, d = std::sqrt( u( rng ) ) * r;
			const float fx = x + std::cos( a ) * d, fz = z + std::sin( a ) * d;
			if( !Inside( fx, fz ) ) continue;
			if( NormalAt( fx, fz ).y < 0.72f && brush.foliage != FoliageKind::Rock ) continue;   // no trees on cliffs
			bool crowded = false;
			for( const auto& f : m_foliage )
				if( std::fabs( f.x - fx ) < minGap && std::fabs( f.z - fz ) < minGap && std::hypot( f.x - fx, f.z - fz ) < minGap ) { crowded = true; break; }
			if( crowded ) continue;
			m_foliage.push_back( { fx, fz, 0.75f + u( rng ) * 0.6f, u( rng ) * 2 * kPi, brush.foliage } );
			++added;
		}
		if( added ) ++m_foliageVersion;
		return added;
	}

	const int n = m_res + 1;
	auto toGrid = [&]( float v ) { return ( v / m_size + 0.5f ) * m_res; };
	const int i0 = std::max( 0, int( std::floor( toGrid( x - r ) ) ) ), i1 = std::min( m_res, int( std::ceil( toGrid( x + r ) ) ) );
	const int j0 = std::max( 0, int( std::floor( toGrid( z - r ) ) ) ), j1 = std::min( m_res, int( std::ceil( toGrid( z + r ) ) ) );
	const std::vector<float> old = brush.mode == Brush::Smooth ? m_h : std::vector<float>();
	// Ramp: heights along the drag, from where it started to where it is now
	const float rdx = brush.rampTo.x - brush.rampFrom.x, rdz = brush.rampTo.z - brush.rampFrom.z;
	const float rlen2 = std::max( 1e-6f, rdx * rdx + rdz * rdz );
	int changed = 0;
	for( int j = j0; j <= j1; ++j )
		for( int i = i0; i <= i1; ++i )
		{
			const float vx = ( float( i ) / m_res - 0.5f ) * m_size, vz = ( float( j ) / m_res - 0.5f ) * m_size;
			const float d = std::hypot( vx - x, vz - z );
			if( d > r ) continue;
			const float f = Falloff( d, r, brush.falloff );
			const size_t k = size_t( j * n + i );
			const float w = std::min( 1.0f, brush.strength * f );
			switch( brush.mode )
			{
			case Brush::Raise: m_h[k] += brush.strength * f; break;
			case Brush::Lower: m_h[k] -= brush.strength * f; break;
			case Brush::Flatten: m_h[k] += ( brush.height - m_h[k] ) * w; break;
			case Brush::Ramp:
			{
				const float t = Clamp( ( ( vx - brush.rampFrom.x ) * rdx + ( vz - brush.rampFrom.z ) * rdz ) / rlen2, 0.0f, 1.0f );
				const float target = brush.rampFromH + ( brush.rampToH - brush.rampFromH ) * t;
				m_h[k] += ( target - m_h[k] ) * w;
				break;
			}
			case Brush::Noise: m_h[k] += Fbm( vx / 12.0f, vz / 12.0f, brush.seed, 4 ) * brush.strength * f; break;
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
				m_h[k] += ( s / m - m_h[k] ) * w;
				break;
			}
			case Brush::Paint:
			{
				// move weight toward the chosen layer; the four always add up to 255
				float wl[kLayers];
				for( int l = 0; l < kLayers; ++l ) wl[l] = m_w[k * 4 + size_t( l )] / 255.0f;
				for( int l = 0; l < kLayers; ++l ) wl[l] += ( ( l == brush.layer ? 1.0f : 0.0f ) - wl[l] ) * w;
				int sum = 0;
				for( int l = 0; l < kLayers; ++l )
				{
					m_w[k * 4 + size_t( l )] = uint8_t( Clamp( std::round( wl[l] * 255.0f ), 0.0f, 255.0f ) );
					sum += m_w[k * 4 + size_t( l )];
				}
				m_w[k * 4 + size_t( brush.layer )] = uint8_t( Clamp( float( m_w[k * 4 + size_t( brush.layer )] + 255 - sum ), 0.0f, 255.0f ) );
				break;
			}
			default: continue;
			}
			++changed;
		}
	if( changed ) ++m_version;
	return changed;
}

void Terrain::Generate( uint32_t seed, float height, float featureSize, int octaves, bool add )
{
	const int n = m_res + 1;
	const float fs = std::max( 1.0f, featureSize );
	for( int j = 0; j < n; ++j )
		for( int i = 0; i < n; ++i )
		{
			const float x = ( float( i ) / m_res - 0.5f ) * m_size, z = ( float( j ) / m_res - 0.5f ) * m_size;
			// ridged fbm on top of soft hills: valleys stay walkable, peaks get sharp
			const float hills = Fbm( x / fs, z / fs, seed, std::max( 1, octaves ) ) * 0.5f + 0.5f;
			const float ridge = 1.0f - std::fabs( Fbm( x / ( fs * 0.7f ), z / ( fs * 0.7f ), seed + 77, std::max( 1, octaves - 1 ) ) );
			const float h = ( hills * 0.75f + ridge * ridge * 0.25f ) * height;
			// fade to zero at the borders so neighbouring terrains meet
			const float edge = Clamp( std::min( std::min( float( i ), float( m_res - i ) ), std::min( float( j ), float( m_res - j ) ) ) / ( m_res * 0.08f ), 0.0f, 1.0f );
			const size_t k = size_t( j * n + i );
			m_h[k] = ( add ? m_h[k] : 0.0f ) + h * edge;
		}
	++m_version;
}

void Terrain::ClearFoliage()
{
	m_foliage.clear();
	++m_foliageVersion;
}

bool Terrain::Raycast( const Vector3& origin, const Vector3& dir, float maxDist, Vector3& hit ) const
{
	const float step = std::max( 0.05f, m_size / m_res * 0.25f );
	bool prevAbove = origin.y >= HeightAt( origin.x, origin.z ) || !Inside( origin.x, origin.z );
	for( float t = step; t <= maxDist; t += step )
	{
		const Vector3 p = origin + dir * t;
		if( !Inside( p.x, p.z ) )
		{
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
		prevAbove = above;
	}
	return false;
}

json Terrain::Save() const
{
	json fol = json::array();
	for( const auto& f : m_foliage )
		fol.push_back( { std::round( f.x * 100 ) / 100, std::round( f.z * 100 ) / 100, std::round( f.scale * 100 ) / 100, std::round( f.yaw * 100 ) / 100, int( f.kind ) } );
	json lay = json::array();
	for( const auto& l : layers ) lay.push_back( { { "name", l.name }, { "color", ToHex( l.color ) } } );
	return { { "res", m_res }, { "size", m_size }, { "heights", Encode64( reinterpret_cast<const uint8_t*>( m_h.data() ), m_h.size() * sizeof( float ) ) },
			 { "weights", Encode64( m_w.data(), m_w.size() ) }, { "foliage", fol }, { "layers", lay }, { "autoShader", autoShader },
			 { "slopeDeg", slopeDeg }, { "snowHeight", snowHeight } };
}

bool Terrain::Load( const json& t )
{
	Terrain fresh( t.value( "res", 128 ), t.value( "size", 256.0f ) );
	const auto h = Decode64( t.value( "heights", std::string() ) );
	if( !h.empty() )
	{
		if( h.size() != fresh.m_h.size() * sizeof( float ) ) return false;
		std::memcpy( fresh.m_h.data(), h.data(), h.size() );
	}
	const auto w = Decode64( t.value( "weights", std::string() ) );
	if( !w.empty() )
	{
		if( w.size() != fresh.m_w.size() ) return false;
		fresh.m_w = w;
	}
	if( t.contains( "foliage" ) && t["foliage"].is_array() )
		for( const auto& f : t["foliage"] )
			if( f.is_array() && f.size() == 5 )
				fresh.m_foliage.push_back( { f[0].get<float>(), f[1].get<float>(), f[2].get<float>(), f[3].get<float>(),
											 FoliageKind( std::min( 4, std::max( 0, f[4].get<int>() ) ) ) } );
	if( t.contains( "layers" ) && t["layers"].is_array() )
		for( size_t l = 0; l < std::min<size_t>( kLayers, t["layers"].size() ); ++l )
		{
			fresh.layers[l].name = t["layers"][l].value( "name", fresh.layers[l].name );
			fresh.layers[l].color = HexColor( t["layers"][l].value( "color", std::string() ), fresh.layers[l].color );
		}
	fresh.autoShader = t.value( "autoShader", true );
	fresh.slopeDeg = t.value( "slopeDeg", 38.0f );
	fresh.snowHeight = t.value( "snowHeight", 40.0f );
	fresh.m_version = m_version + 1;
	fresh.m_foliageVersion = m_foliageVersion + 1;
	fresh.m_shadeVersion = m_shadeVersion + 1;
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

Entity& Scene::Create( ActorType type, const std::string& name, uint32_t parent )
{
	Entity e;
	e.id = nextId++;
	e.type = type;
	e.parent = Find( parent ) ? parent : 0;
	std::string stem = InfoOf( type ).label;
	stem.erase( std::remove( stem.begin(), stem.end(), ' ' ), stem.end() );
	e.name = name.empty() ? UniqueName( stem ) : name;
	e.props = DefaultProps( type );
	if( type == ActorType::Terrain ) e.terrain = std::make_shared<Terrain>();
	m_entities.push_back( std::move( e ) );
	return m_entities.back();
}

bool Scene::Remove( uint32_t id )
{
	if( !Find( id ) ) return false;
	for( uint32_t c : Children( id ) ) Remove( c );
	m_entities.erase( std::remove_if( m_entities.begin(), m_entities.end(), [id]( const Entity& e ) { return e.id == id; } ), m_entities.end() );
	return true;
}

Entity* Scene::Find( uint32_t id )
{
	if( !id ) return nullptr;
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
std::vector<uint32_t> Scene::Children( uint32_t id ) const
{
	std::vector<uint32_t> out;
	for( const auto& e : m_entities )
		if( e.parent == id ) out.push_back( e.id );
	return out;
}
bool Scene::IsAncestor( uint32_t ancestor, uint32_t id ) const
{
	for( const Entity* e = Find( id ); e && e->parent; e = Find( e->parent ) )
		if( e->parent == ancestor ) return true;
	return false;
}
bool Scene::SetParent( uint32_t id, uint32_t parent )
{
	Entity* e = Find( id );
	if( !e || id == parent || ( parent && ( !Find( parent ) || IsAncestor( id, parent ) ) ) ) return false;
	const Matrix world = WorldMatrix( id );
	e->parent = parent;
	e->transform = Decompose( parent ? world * Inverse( WorldMatrix( parent ) ) : world );
	return true;
}
void Scene::Clear()
{
	m_entities.clear();
	nextId = 1;
	settings = DefaultWorldSettings();
}

Matrix Scene::WorldMatrix( uint32_t id ) const
{
	const Entity* e = Find( id );
	if( !e ) return IdentityMatrix();
	Matrix m = e->transform.Local();
	for( int guard = 0; e->parent && guard < 64; ++guard )
	{
		e = Find( e->parent );
		if( !e ) break;
		m = m * e->transform.Local();
	}
	return m;
}
Vector3 Scene::WorldPosition( uint32_t id ) const
{
	const Matrix m = WorldMatrix( id );
	return Vector3( m._41, m._42, m._43 );
}
bool Scene::Visible( uint32_t id ) const
{
	for( const Entity* e = Find( id ); e; e = Find( e->parent ) )
		if( !e->visible ) return false;
	return true;
}

Terrain* Scene::FirstTerrain( uint32_t* id )
{
	for( auto& e : m_entities )
		if( e.terrain )
		{
			if( id ) *id = e.id;
			return e.terrain.get();
		}
	return nullptr;
}

float Scene::GroundAt( float x, float z, bool* found ) const
{
	bool any = false;
	float best = 0.0f;
	for( const auto& e : m_entities )
	{
		if( e.type != ActorType::Terrain || !e.terrain || !Visible( e.id ) ) continue;
		const Vector3 p = WorldPosition( e.id );   // terrains translate only
		const float lx = x - p.x, lz = z - p.z;
		if( !e.terrain->Inside( lx, lz ) ) continue;
		const float h = e.terrain->HeightAt( lx, lz ) + p.y;
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
		if( e.type != ActorType::Terrain || !e.terrain || !Visible( e.id ) ) continue;
		const Vector3 p = WorldPosition( e.id );
		Vector3 h;
		if( e.terrain->Raycast( origin - p, dir, 6000.0f, h ) )
		{
			const Vector3 w = h + p;
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
	uint32_t best = 0;
	float bestT = 1e30f;
	for( const auto& e : m_entities )
	{
		if( !Visible( e.id ) || e.type == ActorType::Terrain || e.type == ActorType::Zone ) continue;
		const Matrix w = WorldMatrix( e.id );
		const float sx = Length( Vector3( w._11, w._12, w._13 ) ), sy = Length( Vector3( w._21, w._22, w._23 ) ), sz = Length( Vector3( w._31, w._32, w._33 ) );
		float radius = 0.75f * std::max( sx, std::max( sy, sz ) );
		Vector3 c( w._41, w._42, w._43 );
		if( e.type == ActorType::Mesh || e.type == ActorType::Model ) c.y += 0.5f * sy;
		if( e.type == ActorType::PlayerStart || e.type == ActorType::QuestGiver ) { c.y += 0.9f; radius = 1.0f; }
		if( e.type == ActorType::CreatureSpawn ) { c.y += 1.0f; radius = 1.0f; }
		if( e.type == ActorType::PointLight || e.type == ActorType::DirLight || e.type == ActorType::Empty ) radius = 0.7f;
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
			{ "id", e.id }, { "parent", e.parent }, { "name", e.name }, { "type", InfoOf( e.type ).id }, { "visible", e.visible }, { "props", e.props },
			{ "position", { e.transform.position.x, e.transform.position.y, e.transform.position.z } },
			{ "rotation", { e.transform.rotation.x, e.transform.rotation.y, e.transform.rotation.z } },
			{ "scale", { e.transform.scale.x, e.transform.scale.y, e.transform.scale.z } },
		};
		if( e.terrain ) a["terrain"] = e.terrain->Save();
		if( !e.components.empty() ) a["components"] = e.components;
		actors.push_back( std::move( a ) );
	}
	return { { "format", "cmmo-level" }, { "version", 2 }, { "name", levelName }, { "nextId", nextId }, { "settings", settings }, { "actors", actors } };
}

bool Scene::FromJson( const json& doc, std::string* error )
{
	auto fail = [&]( const std::string& why ) { if( error ) *error = why; return false; };
	if( !doc.is_object() || doc.value( "format", "" ) != "cmmo-level" ) return fail( "not a Carbon MMO level" );
	if( doc.value( "version", 0 ) > 2 ) return fail( "level made by a newer editor" );
	Scene fresh;
	try
	{
		if( doc.contains( "settings" ) && doc["settings"].is_object() ) fresh.settings.update( doc["settings"] );
		for( const auto& a : doc.at( "actors" ) )
		{
			Entity e;
			e.id = a.at( "id" ).get<uint32_t>();
			e.parent = a.value( "parent", 0u );
			e.name = a.value( "name", "" );
			e.type = TypeFromId( a.value( "type", "empty" ) );
			e.visible = a.value( "visible", true );
			e.props = DefaultProps( e.type );
			if( a.contains( "props" ) && a["props"].is_object() ) e.props.update( a["props"] );
			if( a.contains( "components" ) && a["components"].is_array() )
				for( const auto& c : a["components"] )
					if( c.is_object() && c.contains( "type" ) ) e.components.push_back( c );
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
				e.terrain = std::make_shared<Terrain>();
				if( !e.terrain->Load( a.value( "terrain", json::object() ) ) ) return fail( "terrain data of " + e.name + " is damaged" );
			}
			fresh.nextId = std::max( fresh.nextId, e.id + 1 );
			fresh.m_entities.push_back( std::move( e ) );
		}
		fresh.nextId = std::max( fresh.nextId, doc.value( "nextId", 1u ) );
		for( auto& e : fresh.m_entities )
			if( e.parent && !fresh.Find( e.parent ) ) e.parent = 0;
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
	m_gravity = Num( m_world.settings, "gravity", 20.0f );
	for( const auto& e : m_world.Entities() )
	{
		if( e.type == ActorType::PlayerStart && m_world.Visible( e.id ) )
		{
			m_pos = m_world.WorldPosition( e.id );
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
	m_spawn = m_pos;
	m_spawnYaw = m_yaw;

	abilities = { { "Strike", "fist", 0.0f, 4.0f, 14.0f }, { "Heroic Blow", "bolt", 6.0f, 4.0f, 30.0f },
				  { "Fireball", "fire", 3.0f, 28.0f, 22.0f }, { "Mend", "heart", 12.0f, 0.0f, -35.0f } };

	for( const auto& e : m_world.Entities() )
	{
		if( !m_world.Visible( e.id ) ) continue;
		if( e.type == ActorType::QuestGiver )
		{
			Quest q;
			q.giverId = e.id;
			q.name = Str( e.props, "quest", "A Task" );
			q.target = Str( e.props, "target", "Wolf" );
			q.text = Str( e.props, "text", "" );
			q.done = Str( e.props, "done", "" );
			q.need = std::max( 1, e.props.value( "count", 3 ) );
			q.rewardXp = e.props.value( "rewardXp", 100 );
			quests.push_back( q );
		}
		if( e.type != ActorType::CreatureSpawn ) continue;
		const int count = std::max( 0, std::min( 50, e.props.value( "count", 3 ) ) );
		const Vector3 home = m_world.WorldPosition( e.id );
		for( int i = 0; i < count; ++i )
		{
			Creature c;
			c.spawnId = e.id;
			c.kind = Str( e.props, "creature", "Creature" );
			c.name = c.kind;
			c.home = home;
			c.wander = Num( e.props, "wander", 6.0f );
			c.speed = Num( e.props, "speed", 2.5f );
			c.aggro = Num( e.props, "aggro", 9.0f );
			c.hostile = e.props.value( "hostile", true );
			c.level = e.props.value( "level", 1 );
			c.maxHp = c.hp = Num( e.props, "health", 40.0f + 15.0f * c.level );
			c.damage = Num( e.props, "damage", 4.0f + 2.0f * c.level );
			c.respawn = 0;
			c.color = HexColor( Str( e.props, "color", "#8c6d52" ) );
			const float a = Rand() * 2 * kPi, r = std::sqrt( Rand() ) * c.wander;
			c.position = Vector3( home.x + std::cos( a ) * r, 0, home.z + std::sin( a ) * r );
			c.position.y = Ground( c.position.x, c.position.z, home.y );
			c.wait = Rand() * 2;
			m_creatures.push_back( c );
		}
	}
	// components -> behaviours (Gameplay module), colliders -> physics (Physics module)
	m_physics = std::make_unique<PhysicsWorld>();
	for( const auto& e : m_world.Entities() )
		for( const auto& c : e.components )
		{
			const ComponentInfo* info = FindComponentType( c.value( "type", std::string() ) );
			if( !info || !info->make ) continue;
			auto b = info->make();
			b->actor = e.id;
			b->config = c;
			m_behaviours.push_back( std::move( b ) );
		}
	for( auto& b : m_behaviours ) b->Start( *this );
	m_physics->Build( m_world );
	Zones();
}

PlaySession::~PlaySession() = default;

const std::vector<Body>& PlaySession::Bodies() const { return m_physics->Bodies(); }

void PlaySession::Message( const std::string& text )
{
	m_log.push_back( text );
	toast = text;
	toastFor = 4.0f;
}

void PlaySession::Heal( float amount )
{
	if( deadFor > 0 ) return;
	const float before = hp;
	hp = std::min( maxHp, hp + amount );
	if( hp > before ) floats.push_back( { m_pos + Vector3( 0, 2.2f, 0 ), "+" + std::to_string( int( hp - before ) ), 0, true } );
}

void PlaySession::Damage( float amount )
{
	if( deadFor > 0 ) return;
	hp -= amount;
	floats.push_back( { m_pos + Vector3( 0, 2.2f, 0 ), "-" + std::to_string( int( amount ) ), 0, false } );
	if( hp <= 0 )
	{
		hp = 0;
		deadFor = 5;
		m_log.push_back( "You died." );
	}
}

void PlaySession::AddXp( int amount ) { GainXp( amount ); }

void PlaySession::Triggers()
{
	std::vector<uint32_t> now;
	if( m_possess && deadFor <= 0 ) m_physics->Triggers( m_pos, kRadius, kHeight, now );
	for( uint32_t id : now )
		if( std::find( m_inside.begin(), m_inside.end(), id ) == m_inside.end() )
		{
			const Entity* e = m_world.Find( id );
			if( e && e->type == ActorType::TriggerBox && e->components.empty() ) m_log.push_back( "Entered " + e->name );
			for( auto& b : m_behaviours )
				if( b->actor == id ) b->Enter( *this );
		}
	for( uint32_t id : m_inside )
		if( std::find( now.begin(), now.end(), id ) == now.end() )
			for( auto& b : m_behaviours )
				if( b->actor == id ) b->Exit( *this );
	m_inside = std::move( now );
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
	dt = Clamp( dt, 0.0f, 0.1f );
	m_time += dt;
	for( auto& b : m_behaviours ) b->Tick( *this, m_time, dt );
	m_physics->Build( m_world );   // colliders where the actors are now (movers, rotators)
	if( toastFor > 0 ) toastFor -= dt;
	if( m_possess )
	{
		if( deadFor > 0 )
		{
			deadFor -= dt;
			if( deadFor <= 0 )
			{
				m_pos = m_spawn;
				m_yaw = m_camYaw = m_spawnYaw;
				hp = maxHp;
				m_log.push_back( "You return to life at the start." );
			}
		}
		else
		{
			MovePlayer( dt, in );
			Triggers();
			Combat( dt, in );
			Zones();
		}
	}
	MoveCreatures( dt );
	for( auto& f : floats ) f.age += dt;
	floats.erase( std::remove_if( floats.begin(), floats.end(), []( const FloatText& f ) { return f.age > 1.6f; } ), floats.end() );
	if( zoneBanner > 0 ) zoneBanner -= dt;
}

void PlaySession::MovePlayer( float dt, const PlayInput& in )
{
	if( in.turning || in.orbit )
	{
		m_camYaw -= in.mouseDX * 0.005f;
		m_camPitch = Clamp( m_camPitch - in.mouseDY * 0.005f, -1.35f, 0.6f );
		if( in.turning ) m_yaw = m_camYaw;
	}
	if( in.wheel != 0.0f ) m_camDist = Clamp( m_camDist * ( in.wheel > 0 ? 1.12f : 1.0f / 1.12f ), 1.5f, 40.0f );
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
	m_physics->PushOut( m_pos, kRadius, kHeight );   // walls, crates, tents
	const float ground = std::max( Ground( m_pos.x, m_pos.z, m_baseY ), m_physics->FloorUnder( m_pos, kRadius ) );
	if( in.jump && m_onGround )
	{
		m_vy = m_jump;
		m_onGround = false;
	}
	m_vy -= m_gravity * dt;
	m_pos.y += m_vy * dt;
	if( m_pos.y <= ground )
	{
		m_pos.y = ground;
		m_vy = 0;
		m_onGround = true;
	}
}

void PlaySession::GainXp( int amount )
{
	xp += amount;
	floats.push_back( { m_pos + Vector3( 0, 2.6f, 0 ), "+" + std::to_string( amount ) + " XP", 0, true } );
	while( xp >= XpToLevel() )
	{
		xp -= XpToLevel();
		++level;
		maxHp += 15;
		hp = maxHp;
		m_log.push_back( "Level up! You are now level " + std::to_string( level ) + "." );
	}
}

bool PlaySession::AcceptQuest( int index )
{
	if( index < 0 || index >= int( quests.size() ) || quests[size_t( index )].state != Quest::Offered ) return false;
	quests[size_t( index )].state = Quest::Active;
	m_log.push_back( "Quest accepted: " + quests[size_t( index )].name );
	return true;
}

bool PlaySession::CompleteQuest( int index )
{
	if( index < 0 || index >= int( quests.size() ) || quests[size_t( index )].state != Quest::Ready ) return false;
	Quest& q = quests[size_t( index )];
	q.state = Quest::Complete;
	m_log.push_back( "Quest complete: " + q.name );
	GainXp( q.rewardXp );
	return true;
}

void PlaySession::Combat( float dt, const PlayInput& in )
{
	gcd = std::max( 0.0f, gcd - dt );
	for( auto& a : abilities ) a.remaining = std::max( 0.0f, a.remaining - dt );
	auto alive = [&]( int i ) { return i >= 0 && i < int( m_creatures.size() ) && m_creatures[size_t( i )].state != Creature::Dead; };
	if( !alive( target ) ) target = -1;

	// Tab: the nearest living creature in front, then the next one
	if( in.tabTarget )
	{
		const Vector3 fwd( -std::sin( m_yaw ), 0, -std::cos( m_yaw ) );
		std::vector<std::pair<float, int>> cands;
		for( int i = 0; i < int( m_creatures.size() ); ++i )
		{
			if( !alive( i ) ) continue;
			const Vector3 d = m_creatures[size_t( i )].position - m_pos;
			const float dist = Length( d );
			if( dist > 45 ) continue;
			const float facing = Dot( Normalize( Vector3( d.x, 0, d.z ) ), fwd );
			cands.push_back( { dist - facing * 8.0f, i } );
		}
		std::sort( cands.begin(), cands.end() );
		if( !cands.empty() )
		{
			auto it = std::find_if( cands.begin(), cands.end(), [&]( const auto& c ) { return c.second == target; } );
			target = ( it == cands.end() || it + 1 == cands.end() ) ? cands.front().second : ( it + 1 )->second;
		}
	}

	auto hit = [&]( int i, float dmg, const char* how ) {
		Creature& c = m_creatures[size_t( i )];
		c.hp -= dmg;
		floats.push_back( { c.position + Vector3( 0, 1.8f, 0 ), std::to_string( int( dmg ) ), 0, false } );
		if( c.state != Creature::Chase ) m_log.push_back( c.name + " is attacked." );
		c.state = Creature::Chase;
		if( c.hp <= 0 )
		{
			c.hp = 0;
			c.state = Creature::Dead;
			c.respawn = Num( m_world.Find( c.spawnId ) ? m_world.Find( c.spawnId )->props : json::object(), "respawn", 15.0f );
			m_log.push_back( std::string( how ) + " kills " + c.name + "." );
			GainXp( 18 + c.level * 8 );
			for( auto& q : quests )
				if( q.state == Quest::Active && q.target == c.kind && q.have < q.need )
				{
					++q.have;
					if( q.have >= q.need )
					{
						q.state = Quest::Ready;
						m_log.push_back( q.name + ": done - return to the quest giver." );
					}
				}
			if( target == i ) target = -1;
		}
	};

	if( in.ability >= 1 && in.ability <= int( abilities.size() ) && gcd <= 0 )
	{
		Ability& a = abilities[size_t( in.ability - 1 )];
		if( a.remaining <= 0 )
		{
			if( a.damage < 0 )
			{
				hp = std::min( maxHp, hp - a.damage );
				floats.push_back( { m_pos + Vector3( 0, 2.2f, 0 ), "+" + std::to_string( int( -a.damage ) ), 0, true } );
				a.remaining = a.cooldown;
				gcd = 1.2f;
			}
			else if( alive( target ) && Length( m_creatures[size_t( target )].position - m_pos ) <= a.range )
			{
				hit( target, a.damage, a.name );
				a.remaining = a.cooldown;
				gcd = 1.2f;
			}
			else
				m_log.push_back( alive( target ) ? "Out of range." : "No target - press Tab." );
		}
	}

	// creatures: chase and swing at the player
	bool inCombat = false;
	for( auto& c : m_creatures )
	{
		if( c.state != Creature::Chase ) continue;
		inCombat = true;
		c.swing -= dt;
		if( Length( c.position - m_pos ) < 2.2f && c.swing <= 0 )
		{
			c.swing = 2.0f;
			hp -= c.damage;
			floats.push_back( { m_pos + Vector3( 0, 2.2f, 0 ), "-" + std::to_string( int( c.damage ) ), 0, false } );
			if( hp <= 0 )
			{
				hp = 0;
				deadFor = 3.0f;
				target = -1;
				m_log.push_back( "You died. Respawning..." );
				for( auto& o : m_creatures )
					if( o.state == Creature::Chase ) { o.state = Creature::Return; o.target = o.home; o.hasTarget = true; o.hp = o.maxHp; }
				return;
			}
		}
	}
	if( !inCombat ) hp = std::min( maxHp, hp + maxHp * 0.03f * dt );   // out of combat: regenerate

	// F: talk to the quest giver in reach
	if( in.interact )
	{
		talkingTo = -1;
		for( int i = 0; i < int( quests.size() ); ++i )
			if( Length( m_world.WorldPosition( quests[size_t( i )].giverId ) - m_pos ) < 4.5f ) { talkingTo = i; break; }
		if( talkingTo < 0 ) m_log.push_back( "Nobody to talk to here." );
	}
	if( talkingTo >= 0 && Length( m_world.WorldPosition( quests[size_t( talkingTo )].giverId ) - m_pos ) > 7.0f ) talkingTo = -1;
}

void PlaySession::Zones()
{
	std::string now, info;
	for( const auto& e : m_world.Entities() )
	{
		if( e.type != ActorType::Zone || !m_world.Visible( e.id ) ) continue;
		const Vector3 c = m_world.WorldPosition( e.id );
		const auto& s = e.props["size"];
		const float hx = s.is_array() ? s[0].get<float>() * 0.5f : 30, hy = s.is_array() ? s[1].get<float>() * 0.5f : 20, hz = s.is_array() ? s[2].get<float>() * 0.5f : 30;
		if( std::fabs( m_pos.x - c.x ) <= hx && std::fabs( m_pos.y - c.y ) <= hy && std::fabs( m_pos.z - c.z ) <= hz )
		{
			now = Str( e.props, "zone", e.name );
			info = "Level " + std::to_string( e.props.value( "levelMin", 1 ) ) + "-" + std::to_string( e.props.value( "levelMax", 5 ) ) +
				   ( e.props.value( "pvp", false ) ? "  -  PvP" : "" );
			break;
		}
	}
	if( now != zone )
	{
		zone = now;
		zoneInfo = info;
		if( !zone.empty() )
		{
			zoneBanner = 4.0f;
			m_log.push_back( "Entering " + zone );
		}
	}
}

void PlaySession::MoveCreatures( float dt )
{
	for( auto& c : m_creatures )
	{
		if( c.state == Creature::Dead )
		{
			c.respawn -= dt;
			if( c.respawn <= 0 )
			{
				c.hp = c.maxHp;
				c.state = Creature::Idle;
				c.position = c.home;
				c.position.y = Ground( c.position.x, c.position.z, c.home.y );
				c.hasTarget = false;
			}
			continue;
		}
		const bool playerAlive = m_possess && deadFor <= 0;
		const float toPlayer = playerAlive ? Length( m_pos - c.position ) : 1e9f;
		const float fromHome = Length( c.position - c.home );
		const bool chasing = c.state == Creature::Chase;
		if( playerAlive && ( chasing ? toPlayer < c.aggro * 3.0f && fromHome < c.wander + 35.0f : c.hostile && toPlayer < c.aggro ) )
		{
			if( !chasing ) m_log.push_back( c.name + " attacks!" );
			c.state = Creature::Chase;
			c.hasTarget = toPlayer > 1.6f;
			c.target = m_pos;
		}
		else if( chasing )
		{
			c.state = Creature::Return;   // leashed: back home, healed (WoW evade)
			c.target = c.home;
			c.hasTarget = true;
			c.hp = c.maxHp;
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
		else if( c.state == Creature::Chase )
		{
			const Vector3 d = m_pos - c.position;
			c.yaw = std::atan2( -d.x, -d.z );
		}
		m_physics->PushOut( c.position, 0.5f, 1.2f );
		c.position.y = std::max( Ground( c.position.x, c.position.z, c.home.y ), m_physics->FloorUnder( c.position, 0.5f ) );
	}
}

void PlaySession::CameraEyeTarget( Vector3& eye, Vector3& target ) const
{
	target = m_pos + Vector3( 0, 1.6f, 0 );
	const float cp = std::cos( m_camPitch );
	eye = target + Vector3( std::sin( m_camYaw ) * cp, -std::sin( m_camPitch ), std::cos( m_camYaw ) * cp ) * m_camDist;
	const float g = Ground( eye.x, eye.z, -1e9f );
	if( eye.y < g + 0.4f ) eye.y = g + 0.4f;
}

std::vector<std::string> PlaySession::TakeLog()
{
	std::vector<std::string> out;
	out.swap( m_log );
	return out;
}
}
