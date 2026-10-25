// MODULE: editor.render
#include "editor/Renderer.h"

#include "world/Physics.h"

#include <algorithm>
#include <cmath>
#include <filesystem>
#include <random>

#define CGLTF_IMPLEMENTATION
#include "cgltf.h"

#include "Vector4.h"

#include "editor/GL.h"

using namespace cmmo::gl;
using cmmo::world::ActorType;

namespace cmmo::editor
{
namespace
{
constexpr float kPi = 3.14159265358979f;

const char* kVS = R"(#version 330 core
layout(location = 0) in vec3 aPos;
layout(location = 1) in vec3 aNrm;
layout(location = 2) in vec3 aCol;
uniform mat4 uMVP;
uniform mat4 uModel;
out vec3 vN;
out vec3 vC;
out vec3 vW;
void main() {
  gl_Position = uMVP * vec4(aPos, 1.0);
  vW = (uModel * vec4(aPos, 1.0)).xyz;
  vN = mat3(uModel) * aNrm;
  vC = aCol;
}
)";

const char* kFS = R"(#version 330 core
in vec3 vN;
in vec3 vC;
in vec3 vW;
uniform vec3 uTint;
uniform float uVertexColor;
uniform float uUnlit;
uniform float uAlpha;
uniform float uSky;
uniform vec3 uSkyLow;
uniform vec3 uSunDir;
uniform vec3 uSunColor;
uniform vec3 uAmbient;
uniform int uNumPoints;
uniform vec3 uPointPos[8];
uniform vec3 uPointCol[8];
uniform float uPointRange[8];
uniform vec3 uEye;
uniform vec3 uFog;
uniform float uFogDensity;
out vec4 frag;
void main() {
  if (uSky > 0.5) {                       // sky dome: horizon colour -> sky colour, a sun glow
    vec3 d = normalize(vW - uEye);
    float glow = pow(max(dot(d, -uSunDir), 0.0), 64.0);
    frag = vec4(mix(uSkyLow, uTint, vC.r) + uSunColor * glow * 0.6, 1.0);
    return;
  }
  vec3 base = mix(uTint, vC * uTint, uVertexColor);
  if (uUnlit > 0.5) { frag = vec4(base, uAlpha); return; }
  vec3 n = normalize(vN);
  float ndl = max(dot(n, -uSunDir), 0.0);
  float hemi = 0.5 + 0.5 * n.y;           // sky light from above, ground bounce from below
  vec3 light = uAmbient * (0.65 + 0.55 * hemi) + uSunColor * ndl;
  for (int i = 0; i < uNumPoints; ++i) {
    vec3 d = uPointPos[i] - vW;
    float dist = length(d);
    float att = clamp(1.0 - dist / uPointRange[i], 0.0, 1.0);
    light += uPointCol[i] * max(dot(n, d / max(dist, 1e-4)), 0.0) * att * att;
  }
  vec3 c = base * light;
  float f = 1.0 - exp(-uFogDensity * length(vW - uEye));
  frag = vec4(mix(c, uFog, clamp(f, 0.0, 0.9)), uAlpha);
}
)";

struct V
{
	float p[3], n[3], c[3];
};

Renderer::Mesh Upload( const std::vector<V>& verts, const std::vector<uint32_t>& idx, unsigned prim )
{
	Renderer::Mesh m;
	m.prim = prim;
	glGenVertexArrays( 1, &m.vao );
	glBindVertexArray( m.vao );
	glGenBuffers( 1, &m.vbo );
	glBindBuffer( GL_ARRAY_BUFFER, m.vbo );
	glBufferData( GL_ARRAY_BUFFER, GLsizeiptr( std::max<size_t>( 1, verts.size() ) * sizeof( V ) ), verts.empty() ? nullptr : verts.data(), GL_DYNAMIC_DRAW );
	for( int a = 0; a < 3; ++a )
	{
		glEnableVertexAttribArray( GLuint( a ) );
		glVertexAttribPointer( GLuint( a ), 3, GL_FLOAT, GL_FALSE, sizeof( V ), reinterpret_cast<void*>( size_t( a * 12 ) ) );
	}
	if( !idx.empty() )
	{
		glGenBuffers( 1, &m.ibo );
		glBindBuffer( GL_ELEMENT_ARRAY_BUFFER, m.ibo );
		glBufferData( GL_ELEMENT_ARRAY_BUFFER, GLsizeiptr( idx.size() * 4 ), idx.data(), GL_STATIC_DRAW );
		m.count = int( idx.size() );
	}
	else
		m.count = int( verts.size() );
	m.triangles = prim == GL_TRIANGLES ? m.count / 3 : 0;
	glBindVertexArray( 0 );
	return m;
}
void Drop( Renderer::Mesh& m )
{
	if( m.vao ) glDeleteVertexArrays( 1, &m.vao );
	if( m.vbo ) glDeleteBuffers( 1, &m.vbo );
	if( m.ibo ) glDeleteBuffers( 1, &m.ibo );
	m = Renderer::Mesh();
}

V Vert( float x, float y, float z, float nx, float ny, float nz, float r = 1, float g = 1, float b = 1 )
{
	return V{ { x, y, z }, { nx, ny, nz }, { r, g, b } };
}

// ---- unit primitives (about 1 m), centred on the origin unless noted
void Box( std::vector<V>& v, std::vector<uint32_t>& i )
{
	const float n[6][3] = { { 1, 0, 0 }, { -1, 0, 0 }, { 0, 1, 0 }, { 0, -1, 0 }, { 0, 0, 1 }, { 0, 0, -1 } };
	for( int f = 0; f < 6; ++f )
	{
		const float* N = n[f];
		float u[3] = { N[1], N[2], N[0] }, w[3] = { N[1] * u[2] - N[2] * u[1], N[2] * u[0] - N[0] * u[2], N[0] * u[1] - N[1] * u[0] };
		const uint32_t b = uint32_t( v.size() );
		for( int k = 0; k < 4; ++k )
		{
			const float su = ( k == 1 || k == 2 ) ? 0.5f : -0.5f, sw = ( k >= 2 ) ? 0.5f : -0.5f;
			v.push_back( Vert( N[0] * 0.5f + u[0] * su + w[0] * sw, N[1] * 0.5f + u[1] * su + w[1] * sw, N[2] * 0.5f + u[2] * su + w[2] * sw, N[0], N[1], N[2] ) );
		}
		i.insert( i.end(), { b, b + 1, b + 2, b, b + 2, b + 3 } );
	}
}
void Sphere( std::vector<V>& v, std::vector<uint32_t>& i, float r = 0.5f, int seg = 20, int rings = 12, float yOff = 0, float stretch = 0 )
{
	const uint32_t b = uint32_t( v.size() );
	for( int y = 0; y <= rings; ++y )
		for( int x = 0; x <= seg; ++x )
		{
			const float th = kPi * y / rings, ph = 2 * kPi * x / seg;
			const float nx = std::sin( th ) * std::cos( ph ), ny = std::cos( th ), nz = std::sin( th ) * std::sin( ph );
			const float off = ny > 0 ? stretch : -stretch;
			v.push_back( Vert( nx * r, ny * r + yOff + off, nz * r, nx, ny, nz ) );
		}
	for( int y = 0; y < rings; ++y )
		for( int x = 0; x < seg; ++x )
		{
			const uint32_t a = b + uint32_t( y * ( seg + 1 ) + x ), c = a + uint32_t( seg + 1 );
			i.insert( i.end(), { a, c, a + 1, a + 1, c, c + 1 } );
		}
}
void Cylinder( std::vector<V>& v, std::vector<uint32_t>& i, float rTop, float rBot, int seg = 20 )
{
	const uint32_t b = uint32_t( v.size() );
	const float slope = rBot - rTop, len = std::sqrt( 1 + slope * slope );
	for( int x = 0; x <= seg; ++x )
	{
		const float ph = 2 * kPi * x / seg, c = std::cos( ph ), s = std::sin( ph );
		v.push_back( Vert( c * rTop, 0.5f, s * rTop, c / len, slope / len, s / len ) );
		v.push_back( Vert( c * rBot, -0.5f, s * rBot, c / len, slope / len, s / len ) );
	}
	for( int x = 0; x < seg; ++x )
	{
		const uint32_t a = b + uint32_t( x * 2 );
		i.insert( i.end(), { a, a + 1, a + 2, a + 2, a + 1, a + 3 } );
	}
	for( int cap = 0; cap < 2; ++cap )
	{
		const float r = cap ? rBot : rTop, y = cap ? -0.5f : 0.5f, ny = cap ? -1.0f : 1.0f;
		if( r <= 0 ) continue;
		const uint32_t c0 = uint32_t( v.size() );
		v.push_back( Vert( 0, y, 0, 0, ny, 0 ) );
		for( int x = 0; x <= seg; ++x )
		{
			const float ph = 2 * kPi * x / seg;
			v.push_back( Vert( std::cos( ph ) * r, y, std::sin( ph ) * r, 0, ny, 0 ) );
		}
		for( int x = 0; x < seg; ++x ) i.insert( i.end(), { c0, c0 + 1 + uint32_t( x ), c0 + 2 + uint32_t( x ) } );
	}
}
void Plane( std::vector<V>& v, std::vector<uint32_t>& i )
{
	const uint32_t b = uint32_t( v.size() );
	v.push_back( Vert( -0.5f, 0, -0.5f, 0, 1, 0 ) );
	v.push_back( Vert( 0.5f, 0, -0.5f, 0, 1, 0 ) );
	v.push_back( Vert( 0.5f, 0, 0.5f, 0, 1, 0 ) );
	v.push_back( Vert( -0.5f, 0, 0.5f, 0, 1, 0 ) );
	i.insert( i.end(), { b, b + 2, b + 1, b, b + 3, b + 2 } );
}
void Ring( std::vector<V>& v, int seg = 64 )
{
	for( int x = 0; x < seg; ++x )
	{
		const float a = 2 * kPi * x / seg, b = 2 * kPi * ( x + 1 ) / seg;
		v.push_back( Vert( std::cos( a ), 0, std::sin( a ), 0, 1, 0 ) );
		v.push_back( Vert( std::cos( b ), 0, std::sin( b ), 0, 1, 0 ) );
	}
}
void WireBox( std::vector<V>& v )
{
	const float c[8][3] = { { -.5f, -.5f, -.5f }, { .5f, -.5f, -.5f }, { .5f, .5f, -.5f }, { -.5f, .5f, -.5f },
							{ -.5f, -.5f, .5f }, { .5f, -.5f, .5f }, { .5f, .5f, .5f }, { -.5f, .5f, .5f } };
	const int e[12][2] = { { 0, 1 }, { 1, 2 }, { 2, 3 }, { 3, 0 }, { 4, 5 }, { 5, 6 }, { 6, 7 }, { 7, 4 }, { 0, 4 }, { 1, 5 }, { 2, 6 }, { 3, 7 } };
	for( auto& k : e )
		for( int j = 0; j < 2; ++j ) v.push_back( Vert( c[k[j]][0], c[k[j]][1], c[k[j]][2], 0, 1, 0 ) );
}
void Grid( std::vector<V>& v, int half = 60, float step = 2.0f )
{
	for( int k = -half; k <= half; ++k )
	{
		const float shade = k == 0 ? 0.62f : ( k % 5 == 0 ? 0.42f : 0.3f );
		for( V p : { Vert( k * step, 0, -half * step, 0, 1, 0 ), Vert( k * step, 0, half * step, 0, 1, 0 ), Vert( -half * step, 0, k * step, 0, 1, 0 ),
					 Vert( half * step, 0, k * step, 0, 1, 0 ) } )
		{
			p.c[0] = p.c[1] = p.c[2] = shade;
			v.push_back( p );
		}
	}
}
void SkyDome( std::vector<V>& v, std::vector<uint32_t>& i )
{
	Sphere( v, i, 1.0f, 32, 16 );
	for( auto& p : v )
	{
		const float t = std::max( 0.0f, std::min( 1.0f, p.p[1] * 1.8f + 0.08f ) );   // 0 at the horizon -> 1 overhead
		p.c[0] = p.c[1] = p.c[2] = std::sqrt( t );
	}
}

// append `src` transformed (scale, yaw, position) and coloured
void Append( std::vector<V>& out, std::vector<uint32_t>& idx, const std::vector<V>& src, const std::vector<uint32_t>& sidx, float sx, float sy, float sz,
			 float yaw, float tx, float ty, float tz, const Vector3& color )
{
	const uint32_t base = uint32_t( out.size() );
	const float c = std::cos( yaw ), s = std::sin( yaw );
	for( V p : src )
	{
		const float x = p.p[0] * sx, y = p.p[1] * sy, z = p.p[2] * sz;
		p.p[0] = x * c + z * s + tx;
		p.p[1] = y + ty;
		p.p[2] = -x * s + z * c + tz;
		const float nx = p.n[0], nz = p.n[2];
		p.n[0] = nx * c + nz * s;
		p.n[2] = -nx * s + nz * c;
		p.c[0] = color.x;
		p.c[1] = color.y;
		p.c[2] = color.z;
		out.push_back( p );
	}
	for( uint32_t k : sidx ) idx.push_back( base + k );
}

Matrix MakeLookAt( const Vector3& eye, const Vector3& target, const Vector3& up )
{
	const Vector3 z = Normalize( eye - target );
	const Vector3 x = Normalize( Cross( up, z ) );
	const Vector3 y = Cross( z, x );
	return Matrix( x.x, y.x, z.x, 0, x.y, y.y, z.y, 0, x.z, y.z, z.z, 0, -Dot( x, eye ), -Dot( y, eye ), -Dot( z, eye ), 1 );
}
}

// ------------------------------------------------------------------------------------------------ camera
Matrix CameraView::View() const
{
	Vector3 up( 0, 1, 0 );
	if( std::fabs( Dot( Normalize( target - eye ), up ) ) > 0.999f ) up = Vector3( 0, 0, -1 );
	return MakeLookAt( eye, target, up );
}
Matrix CameraView::Projection( float aspect ) const
{
	const float f = 1.0f / std::tan( fovDeg * kPi / 360.0f );
	return Matrix( f / aspect, 0, 0, 0, 0, f, 0, 0, 0, 0, ( farZ + nearZ ) / ( nearZ - farZ ), -1, 0, 0, 2 * farZ * nearZ / ( nearZ - farZ ), 0 );
}
void CameraView::Ray( float px, float py, float w, float h, Vector3& origin, Vector3& dir ) const
{
	const Matrix inv = Inverse( View() * Projection( w / std::max( 1.0f, h ) ) );
	const float nx = px / w * 2 - 1, ny = 1 - py / h * 2;
	const Vector3 a = TransformCoord( Vector3( nx, ny, -1 ), inv ), b = TransformCoord( Vector3( nx, ny, 1 ), inv );
	origin = a;
	dir = Normalize( b - a );
}
bool CameraView::Project( const Vector3& p, float w, float h, float& sx, float& sy ) const
{
	const Vector4 c = Transform( p, View() * Projection( w / std::max( 1.0f, h ) ) );
	if( c.w <= 0.05f ) return false;
	sx = ( c.x / c.w * 0.5f + 0.5f ) * w;
	sy = ( 1.0f - ( c.y / c.w * 0.5f + 0.5f ) ) * h;
	return true;
}

// ------------------------------------------------------------------------------------------------ renderer
bool Renderer::Init( std::string& error )
{
	auto compile = [&]( GLenum kind, const char* src ) -> GLuint {
		const GLuint s = glCreateShader( kind );
		glShaderSource( s, 1, &src, nullptr );
		glCompileShader( s );
		GLint ok = 0;
		glGetShaderiv( s, GL_COMPILE_STATUS, &ok );
		if( !ok )
		{
			char log[2048];
			glGetShaderInfoLog( s, sizeof( log ), nullptr, log );
			error = std::string( "shader: " ) + log;
			return 0;
		}
		return s;
	};
	const GLuint vs = compile( GL_VERTEX_SHADER, kVS ), fs = compile( GL_FRAGMENT_SHADER, kFS );
	if( !vs || !fs ) return false;
	m_program = glCreateProgram();
	glAttachShader( m_program, vs );
	glAttachShader( m_program, fs );
	glLinkProgram( m_program );
	glDeleteShader( vs );
	glDeleteShader( fs );
	GLint ok = 0;
	glGetProgramiv( m_program, GL_LINK_STATUS, &ok );
	if( !ok )
	{
		char log[2048];
		glGetProgramInfoLog( m_program, sizeof( log ), nullptr, log );
		error = std::string( "link: " ) + log;
		return false;
	}
	auto U = [&]( const char* n ) { return glGetUniformLocation( m_program, n ); };
	u_mvp = U( "uMVP" ); u_model = U( "uModel" ); u_tint = U( "uTint" ); u_vcol = U( "uVertexColor" ); u_unlit = U( "uUnlit" );
	u_alpha = U( "uAlpha" ); u_sunDir = U( "uSunDir" ); u_sunCol = U( "uSunColor" ); u_ambient = U( "uAmbient" );
	u_nPoints = U( "uNumPoints" ); u_pointPos = U( "uPointPos" ); u_pointCol = U( "uPointCol" ); u_pointRange = U( "uPointRange" );
	u_eye = U( "uEye" ); u_fog = U( "uFog" ); u_fogDensity = U( "uFogDensity" ); u_sky = U( "uSky" ); u_skyLow = U( "uSkyLow" );

	std::vector<V> v;
	std::vector<uint32_t> i;
	auto make = [&]( const char* name, unsigned prim ) { m_meshes[name] = Upload( v, i, prim ); v.clear(); i.clear(); };
	Box( v, i ); make( "cube", GL_TRIANGLES );
	Sphere( v, i ); make( "sphere", GL_TRIANGLES );
	Cylinder( v, i, 0.5f, 0.5f ); make( "cylinder", GL_TRIANGLES );
	Cylinder( v, i, 0.0f, 0.5f ); make( "cone", GL_TRIANGLES );
	Plane( v, i ); make( "plane", GL_TRIANGLES );
	Sphere( v, i, 0.35f, 16, 12, 0.0f, 0.55f ); make( "capsule", GL_TRIANGLES );
	Ring( v ); make( "ring", GL_LINES );
	WireBox( v ); make( "wirebox", GL_LINES );
	Grid( v ); make( "grid", GL_LINES );
	SkyDome( v, i ); make( "sky", GL_TRIANGLES );
	return glGetError() == GL_NO_ERROR;
}

void Renderer::Shutdown()
{
	for( auto& kv : m_meshes ) Drop( kv.second );
	for( auto& kv : m_terrains ) { Drop( kv.second.mesh ); Drop( kv.second.foliage ); }
	for( auto& kv : m_models ) Drop( kv.second.mesh );
	m_meshes.clear();
	m_terrains.clear();
	m_models.clear();
	if( m_fbo ) glDeleteFramebuffers( 1, &m_fbo );
	if( m_color ) glDeleteTextures( 1, &m_color );
	if( m_depth ) glDeleteRenderbuffers( 1, &m_depth );
	if( m_program ) glDeleteProgram( m_program );
	m_fbo = m_color = m_depth = m_program = 0;
}

void Renderer::EnsureTarget( int w, int h )
{
	w = std::max( 1, w );
	h = std::max( 1, h );
	if( m_fbo && w == m_w && h == m_h ) return;
	if( !m_fbo ) glGenFramebuffers( 1, &m_fbo );
	if( !m_color ) glGenTextures( 1, &m_color );
	if( !m_depth ) glGenRenderbuffers( 1, &m_depth );
	glBindTexture( GL_TEXTURE_2D, m_color );
	glTexImage2D( GL_TEXTURE_2D, 0, GL_RGBA8, w, h, 0, GL_RGBA, GL_UNSIGNED_BYTE, nullptr );
	glTexParameteri( GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR );
	glTexParameteri( GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR );
	glBindRenderbuffer( GL_RENDERBUFFER, m_depth );
	glRenderbufferStorage( GL_RENDERBUFFER, GL_DEPTH24_STENCIL8, w, h );
	glBindFramebuffer( GL_FRAMEBUFFER, m_fbo );
	glFramebufferTexture2D( GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, m_color, 0 );
	glFramebufferRenderbuffer( GL_FRAMEBUFFER, GL_DEPTH_STENCIL_ATTACHMENT, GL_RENDERBUFFER, m_depth );
	glBindFramebuffer( GL_FRAMEBUFFER, 0 );
	m_w = w;
	m_h = h;
}

Renderer::Mesh& Renderer::TerrainMesh( const world::Entity& e )
{
	TerrainGpu& g = m_terrains[e.id];
	const world::Terrain& t = *e.terrain;
	if( g.mesh.vao && g.version == t.Version() && g.shade == t.ShadingVersion() && g.source == &t ) return g.mesh;
	const int res = t.Res(), n = res + 1;
	const float size = t.Size();
	std::vector<V> v( size_t( n * n ) );
	for( int j = 0; j < n; ++j )
		for( int i = 0; i < n; ++i )
		{
			const size_t k = size_t( j * n + i );
			const float x = ( float( i ) / res - 0.5f ) * size, z = ( float( j ) / res - 0.5f ) * size;
			const Vector3 nr = t.NormalAt( x, z ), c = t.ColorAt( i, j );
			v[k] = V{ { x, t.Heights()[k], z }, { nr.x, nr.y, nr.z }, { c.x, c.y, c.z } };
		}
	if( g.mesh.vao && g.source == &t && g.mesh.count == res * res * 6 )
	{
		glBindBuffer( GL_ARRAY_BUFFER, g.mesh.vbo );
		glBufferSubData( GL_ARRAY_BUFFER, 0, GLsizeiptr( v.size() * sizeof( V ) ), v.data() );
	}
	else
	{
		Drop( g.mesh );
		std::vector<uint32_t> idx;
		idx.reserve( size_t( res * res * 6 ) );
		for( int j = 0; j < res; ++j )
			for( int i = 0; i < res; ++i )
			{
				const uint32_t a = uint32_t( j * n + i ), b = a + 1, c = a + uint32_t( n ), d = c + 1;
				idx.insert( idx.end(), { a, c, b, b, c, d } );
			}
		g.mesh = Upload( v, idx, GL_TRIANGLES );
	}
	g.version = t.Version();
	g.shade = t.ShadingVersion();
	g.source = &t;
	g.foliageVersion = 0;   // heights moved: re-seat the foliage
	return g.mesh;
}

Renderer::Mesh& Renderer::FoliageMesh( const world::Entity& e )
{
	TerrainGpu& g = m_terrains[e.id];
	const world::Terrain& t = *e.terrain;
	if( g.foliage.vao && g.foliageVersion == t.FoliageVersion() ) return g.foliage;
	static std::vector<V> trunk, crown, cone, ball, blade;
	static std::vector<uint32_t> trunkI, crownI, coneI, ballI, bladeI;
	if( trunk.empty() )
	{
		Cylinder( trunk, trunkI, 0.18f, 0.26f, 8 );
		Sphere( crown, crownI, 0.5f, 10, 7 );
		Cylinder( cone, coneI, 0.0f, 0.5f, 10 );
		Sphere( ball, ballI, 0.5f, 8, 6 );
		Cylinder( blade, bladeI, 0.0f, 0.05f, 3 );
	}
	std::vector<V> v;
	std::vector<uint32_t> idx;
	for( const auto& f : t.Foliage() )
	{
		const float y = t.HeightAt( f.x, f.z ), s = f.scale;
		const float shade = 0.85f + 0.3f * std::fmod( f.yaw * 3.7f, 1.0f );
		switch( f.kind )
		{
		case world::FoliageKind::Tree:
			Append( v, idx, trunk, trunkI, s, 2.4f * s, s, f.yaw, f.x, y + 1.2f * s, f.z, Vector3( 0.36f, 0.26f, 0.17f ) );
			Append( v, idx, crown, crownI, 3.4f * s, 3.0f * s, 3.4f * s, f.yaw, f.x, y + 3.6f * s, f.z, Vector3( 0.22f, 0.42f, 0.17f ) * shade );
			break;
		case world::FoliageKind::Pine:
			Append( v, idx, trunk, trunkI, 0.8f * s, 2.0f * s, 0.8f * s, f.yaw, f.x, y + 1.0f * s, f.z, Vector3( 0.3f, 0.21f, 0.14f ) );
			Append( v, idx, cone, coneI, 3.0f * s, 3.6f * s, 3.0f * s, f.yaw, f.x, y + 3.2f * s, f.z, Vector3( 0.12f, 0.3f, 0.18f ) * shade );
			Append( v, idx, cone, coneI, 2.2f * s, 2.8f * s, 2.2f * s, f.yaw, f.x, y + 5.0f * s, f.z, Vector3( 0.14f, 0.34f, 0.2f ) * shade );
			break;
		case world::FoliageKind::Bush:
			Append( v, idx, ball, ballI, 1.6f * s, 1.1f * s, 1.6f * s, f.yaw, f.x, y + 0.45f * s, f.z, Vector3( 0.25f, 0.45f, 0.18f ) * shade );
			break;
		case world::FoliageKind::Rock:
			Append( v, idx, ball, ballI, 1.6f * s, 0.9f * s, 1.2f * s, f.yaw, f.x, y + 0.2f * s, f.z, Vector3( 0.48f, 0.47f, 0.45f ) * shade );
			break;
		default:
			for( int b = 0; b < 3; ++b )
				Append( v, idx, blade, bladeI, s, 0.7f * s, s, f.yaw + b * 2.1f, f.x + 0.15f * std::cos( f.yaw + b * 2.1f ), y + 0.35f * s,
						f.z + 0.15f * std::sin( f.yaw + b * 2.1f ), Vector3( 0.38f, 0.6f, 0.22f ) * shade );
		}
	}
	Drop( g.foliage );
	g.foliage = Upload( v, idx, GL_TRIANGLES );
	g.foliageVersion = t.FoliageVersion();
	return g.foliage;
}

const Renderer::Mesh* Renderer::ModelMesh( const std::string& path, std::string* error )
{
	auto it = m_models.find( path );
	if( it != m_models.end() )
	{
		if( error ) *error = it->second.error;
		return it->second.ok ? &it->second.mesh : nullptr;
	}
	ModelGpu& out = m_models[path];
	cgltf_options opt{};
	cgltf_data* data = nullptr;
	if( cgltf_parse_file( &opt, path.c_str(), &data ) != cgltf_result_success || cgltf_load_buffers( &opt, data, path.c_str() ) != cgltf_result_success )
	{
		out.error = "cannot read " + path;
		if( data ) cgltf_free( data );
		if( error ) *error = out.error;
		return nullptr;
	}
	std::vector<V> v;
	std::vector<uint32_t> idx;
	for( cgltf_size ni = 0; ni < data->nodes_count; ++ni )
	{
		const cgltf_node& node = data->nodes[ni];
		if( !node.mesh ) continue;
		float m[16];
		cgltf_node_transform_world( &node, m );   // column-major = Carbon row-vector memory
		const Matrix world( m[0], m[1], m[2], m[3], m[4], m[5], m[6], m[7], m[8], m[9], m[10], m[11], m[12], m[13], m[14], m[15] );
		for( cgltf_size pi = 0; pi < node.mesh->primitives_count; ++pi )
		{
			const cgltf_primitive& prim = node.mesh->primitives[pi];
			if( prim.type != cgltf_primitive_type_triangles ) continue;
			const cgltf_accessor *pos = nullptr, *nrm = nullptr, *colA = nullptr;
			for( cgltf_size a = 0; a < prim.attributes_count; ++a )
			{
				if( prim.attributes[a].type == cgltf_attribute_type_position ) pos = prim.attributes[a].data;
				if( prim.attributes[a].type == cgltf_attribute_type_normal ) nrm = prim.attributes[a].data;
				if( prim.attributes[a].type == cgltf_attribute_type_color && prim.attributes[a].index == 0 ) colA = prim.attributes[a].data;
			}
			if( !pos ) continue;
			Vector3 base( 0.8f, 0.8f, 0.8f );
			if( prim.material && prim.material->has_pbr_metallic_roughness )
			{
				const float* f = prim.material->pbr_metallic_roughness.base_color_factor;
				base = Vector3( f[0], f[1], f[2] );
			}
			const uint32_t first = uint32_t( v.size() );
			for( cgltf_size k = 0; k < pos->count; ++k )
			{
				float p[3] = { 0, 0, 0 }, n[3] = { 0, 1, 0 }, c[4] = { 1, 1, 1, 1 };
				cgltf_accessor_read_float( pos, k, p, 3 );
				if( nrm ) cgltf_accessor_read_float( nrm, k, n, 3 );
				if( colA ) cgltf_accessor_read_float( colA, k, c, 4 );
				const Vector3 wp = TransformCoord( Vector3( p[0], p[1], p[2] ), world ), wn = Normalize( TransformNormal( Vector3( n[0], n[1], n[2] ), world ) );
				v.push_back( Vert( wp.x, wp.y, wp.z, wn.x, wn.y, wn.z, base.x * c[0], base.y * c[1], base.z * c[2] ) );
			}
			if( prim.indices )
				for( cgltf_size k = 0; k < prim.indices->count; ++k ) idx.push_back( first + uint32_t( cgltf_accessor_read_index( prim.indices, k ) ) );
			else
				for( cgltf_size k = 0; k < pos->count; ++k ) idx.push_back( first + uint32_t( k ) );
			if( !nrm )   // flat normals
				for( size_t k = idx.size() - ( prim.indices ? prim.indices->count : pos->count ); k + 2 < idx.size(); k += 3 )
				{
					V& a = v[idx[k]];
					V& b = v[idx[k + 1]];
					V& c = v[idx[k + 2]];
					const Vector3 fn = Normalize( Cross( Vector3( b.p[0] - a.p[0], b.p[1] - a.p[1], b.p[2] - a.p[2] ), Vector3( c.p[0] - a.p[0], c.p[1] - a.p[1], c.p[2] - a.p[2] ) ) );
					for( V* q : { &a, &b, &c } ) { q->n[0] = fn.x; q->n[1] = fn.y; q->n[2] = fn.z; }
				}
		}
	}
	cgltf_free( data );
	if( v.empty() )
	{
		out.error = path + " has no triangle meshes";
		if( error ) *error = out.error;
		return nullptr;
	}
	out.mesh = Upload( v, idx, GL_TRIANGLES );
	out.ok = true;
	return &out.mesh;
}

bool Renderer::ModelInfo( const std::string& path, int* triangles, std::string* error )
{
	const Mesh* m = ModelMesh( path, error );
	if( m && triangles ) *triangles = m->triangles;
	return m != nullptr;
}

void Renderer::Draw( const Mesh& mesh, const Matrix& world, const Vector3& tint, bool vertexColor, bool unlit, float alpha )
{
	const Matrix mvp = world * m_viewProj;
	glUniformMatrix4fv( u_mvp, 1, GL_FALSE, &mvp._11 );   // Carbon row-major + row vectors = GL column-major memory
	glUniformMatrix4fv( u_model, 1, GL_FALSE, &world._11 );
	glUniform3f( u_tint, tint.x, tint.y, tint.z );
	glUniform1f( u_vcol, vertexColor ? 1.0f : 0.0f );
	glUniform1f( u_unlit, unlit || m_mode == ViewMode::Unlit ? 1.0f : 0.0f );
	glUniform1f( u_alpha, alpha );
	glBindVertexArray( mesh.vao );
	if( mesh.ibo ) glDrawElements( mesh.prim, mesh.count, GL_UNSIGNED_INT, nullptr );
	else glDrawArrays( mesh.prim, 0, mesh.count );
	++m_stats.drawCalls;
	m_stats.triangles += mesh.triangles;
}

void Renderer::Render( int width, int height, const FrameInfo& f )
{
	EnsureTarget( width, height );
	m_stats = FrameStats();
	m_mode = f.mode;
	glBindFramebuffer( GL_FRAMEBUFFER, m_fbo );
	glViewport( 0, 0, m_w, m_h );
	const world::Scene* scenePtr = f.play ? &f.play->World() : f.scene;
	if( !scenePtr )
	{
		glClearColor( 0.1f, 0.1f, 0.11f, 1 );
		glClear( GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT );
		glBindFramebuffer( GL_FRAMEBUFFER, 0 );
		return;
	}
	const world::Scene& scene = *scenePtr;
	const bool playing = f.play != nullptr;
	const auto& ws = scene.settings;
	const Vector3 sky = world::HexColor( ws.value( "sky", std::string( "#7aa5d4" ) ) ), horizon = world::HexColor( ws.value( "horizon", std::string( "#c9d9e6" ) ) );
	const Vector3 ambient = world::HexColor( ws.value( "ambient", std::string( "#56606e" ) ) );
	glClearColor( horizon.x, horizon.y, horizon.z, 1 );
	glClear( GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT );
	glEnable( GL_DEPTH_TEST );
	glDisable( GL_CULL_FACE );
	glEnable( GL_BLEND );
	glBlendFunc( GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA );
	m_viewProj = f.camera.View() * f.camera.Projection( float( m_w ) / float( m_h ) );
	glUseProgram( m_program );

	// lights: the first visible Sun (else a default afternoon sun) + up to 8 point lights
	Vector3 sunDir = Normalize( Vector3( -0.45f, -0.8f, -0.35f ) ), sunCol( 1.0f, 0.95f, 0.86f );
	float px[24], pc[24], pr[8];
	int np = 0;
	bool haveSun = false;
	for( const auto& e : scene.Entities() )
	{
		if( !scene.Visible( e.id ) ) continue;
		if( e.type == ActorType::DirLight && !haveSun )
		{
			sunDir = Normalize( TransformNormal( Vector3( 0, -1, 0 ), scene.WorldMatrix( e.id ) ) );
			sunCol = world::HexColor( e.props.value( "color", std::string( "#fff1dc" ) ) ) * e.props.value( "intensity", 1.0f );
			haveSun = true;
		}
		if( e.type == ActorType::PointLight && np < 8 )
		{
			const Vector3 c = world::HexColor( e.props.value( "color", std::string( "#ffb760" ) ) ) * e.props.value( "intensity", 2.0f ), p = scene.WorldPosition( e.id );
			px[np * 3] = p.x; px[np * 3 + 1] = p.y; px[np * 3 + 2] = p.z;
			pc[np * 3] = c.x; pc[np * 3 + 1] = c.y; pc[np * 3 + 2] = c.z;
			pr[np] = std::max( 0.1f, e.props.value( "range", 15.0f ) );
			++np;
		}
	}
	glUniform3f( u_sunDir, sunDir.x, sunDir.y, sunDir.z );
	glUniform3f( u_sunCol, sunCol.x, sunCol.y, sunCol.z );
	glUniform3f( u_ambient, ambient.x, ambient.y, ambient.z );
	glUniform1i( u_nPoints, np );
	if( np )
	{
		glUniform3fv( u_pointPos, np, px );
		glUniform3fv( u_pointCol, np, pc );
		glUniform1fv( u_pointRange, np, pr );
	}
	glUniform3f( u_eye, f.camera.eye.x, f.camera.eye.y, f.camera.eye.z );
	glUniform3f( u_fog, horizon.x, horizon.y, horizon.z );
	glUniform1f( u_fogDensity, ws.value( "fog", 0.0035f ) );
	glUniform3f( u_skyLow, horizon.x, horizon.y, horizon.z );

	// sky dome around the camera
	glDepthMask( GL_FALSE );
	glUniform1f( u_sky, 1.0f );
	Draw( m_meshes["sky"], ScalingMatrix( 1500, 1500, 1500 ) * TranslationMatrix( f.camera.eye ), sky, true, true );
	glUniform1f( u_sky, 0.0f );
	glDepthMask( GL_TRUE );

	if( f.mode == ViewMode::Wireframe ) glPolygonMode( GL_FRONT_AND_BACK, GL_LINE );
	const Matrix I = IdentityMatrix();
	if( f.grid && !playing ) Draw( m_meshes["grid"], TranslationMatrix( 0, -0.04f, 0 ), Vector3( 1, 1, 1 ), true, true, 0.55f );

	const Vector3 selectCol( 1.0f, 0.62f, 0.15f );
	auto outline = [&]( const Mesh& mesh, const Matrix& w ) {
		glPolygonMode( GL_FRONT_AND_BACK, GL_LINE );
		Draw( mesh, w, selectCol, false, true );
		glPolygonMode( GL_FRONT_AND_BACK, f.mode == ViewMode::Wireframe ? GL_LINE : GL_FILL );
	};
	for( const auto& e : scene.Entities() )
	{
		if( !scene.Visible( e.id ) ) continue;
		const bool sel = !playing && e.id == f.selected;
		const Matrix W = scene.WorldMatrix( e.id );
		const Vector3 wp( W._41, W._42, W._43 );
		const Matrix T = TranslationMatrix( wp );   // markers ignore scale and rotation
		switch( e.type )
		{
		case ActorType::Terrain:
		{
			if( !e.terrain ) break;
			const Mesh& tm = TerrainMesh( e );
			Draw( tm, T, Vector3( 1, 1, 1 ), true, false );
			const Mesh& fm = FoliageMesh( e );
			if( fm.count ) Draw( fm, T, Vector3( 1, 1, 1 ), true, false );
			m_stats.foliage += int( e.terrain->Foliage().size() );
			if( sel )
			{
				glEnable( GL_POLYGON_OFFSET_LINE );
				glPolygonOffset( -1, -1 );
				glPolygonMode( GL_FRONT_AND_BACK, GL_LINE );
				Draw( tm, T, selectCol, false, true, 0.18f );
				glPolygonMode( GL_FRONT_AND_BACK, f.mode == ViewMode::Wireframe ? GL_LINE : GL_FILL );
				glDisable( GL_POLYGON_OFFSET_LINE );
			}
			break;
		}
		case ActorType::Mesh:
		{
			std::string shape = e.props.value( "shape", std::string( "cube" ) );
			if( shape != "sphere" && shape != "cylinder" && shape != "cone" && shape != "plane" ) shape = "cube";
			const Matrix lift = shape == "plane" ? I : TranslationMatrix( 0, 0.5f, 0 );   // shapes sit on their pivot
			Draw( m_meshes[shape], lift * W, world::HexColor( e.props.value( "color", std::string( "#b8b2a6" ) ) ), false, false );
			if( sel ) outline( m_meshes[shape], ScalingMatrix( 1.01f, 1.01f, 1.01f ) * lift * W );
			break;
		}
		case ActorType::Model:
		{
			const std::string rel = e.props.value( "path", std::string() );
			std::string err;
			const Mesh* mm = rel.empty() ? nullptr : ModelMesh( ( std::filesystem::path( f.contentDir ) / rel ).string(), &err );
			const Vector3 tint = world::HexColor( e.props.value( "color", std::string( "#ffffff" ) ) );
			if( mm )
			{
				Draw( *mm, W, tint, true, false );
				if( sel ) outline( *mm, W );
			}
			else
				Draw( m_meshes["wirebox"], TranslationMatrix( 0, 0.5f, 0 ) * W, sel ? selectCol : Vector3( 0.9f, 0.4f, 0.4f ), false, true );
			break;
		}
		case ActorType::QuestGiver:
		{
			const Vector3 c = world::HexColor( e.props.value( "color", std::string( "#e8c547" ) ) );
			const Matrix R = RotationYMatrix( e.transform.rotation.y * kPi / 180 ) * T;
			Draw( m_meshes["capsule"], TranslationMatrix( 0, 0.9f, 0 ) * R, Vector3( 0.32f, 0.3f, 0.42f ), false, false );
			Draw( m_meshes["sphere"], ScalingMatrix( 0.5f, 0.5f, 0.5f ) * TranslationMatrix( 0, 1.75f, 0 ) * R, Vector3( 0.86f, 0.7f, 0.56f ), false, false );
			if( !playing )
			{
				Draw( m_meshes["cone"], ScalingMatrix( 0.18f, 0.5f, 0.18f ) * RotationXMatrix( kPi ) * TranslationMatrix( 0, 2.7f, 0 ) * T, c, false, true );
				if( sel ) outline( m_meshes["capsule"], TranslationMatrix( 0, 0.9f, 0 ) * R );
			}
			break;
		}
		default:
		{
			if( playing ) break;   // editor markers are hidden while playing
			const Vector3 c = sel ? selectCol : Vector3( 0.33f, 0.66f, 1.0f );
			glPolygonMode( GL_FRONT_AND_BACK, GL_LINE );
			if( e.type == ActorType::PlayerStart )
			{
				const Matrix R = RotationYMatrix( e.transform.rotation.y * kPi / 180 ) * T;
				Draw( m_meshes["capsule"], TranslationMatrix( 0, 0.9f, 0 ) * R, c, false, true );
				glPolygonMode( GL_FRONT_AND_BACK, GL_FILL );
				Draw( m_meshes["cone"], ScalingMatrix( 0.25f, 0.5f, 0.25f ) * RotationXMatrix( -kPi / 2 ) * TranslationMatrix( 0, 1.5f, -0.5f ) * R, c, false, true );
			}
			else if( e.type == ActorType::CreatureSpawn )
			{
				const Vector3 col = sel ? selectCol : Vector3( 0.95f, 0.38f, 0.3f );
				const float r = e.props.value( "wander", 6.0f );
				Draw( m_meshes["ring"], ScalingMatrix( r, 1, r ) * TranslationMatrix( 0, 0.15f, 0 ) * T, col, false, true );
				glPolygonMode( GL_FRONT_AND_BACK, GL_FILL );
				Draw( m_meshes["cone"], ScalingMatrix( 0.5f, 0.8f, 0.5f ) * RotationXMatrix( kPi ) * TranslationMatrix( 0, 1.2f, 0 ) * T, col, false, true );
			}
			else if( e.type == ActorType::TriggerBox || e.type == ActorType::Zone )
			{
				const auto& s = e.props["size"];
				const Matrix S = s.is_array() && s.size() == 3 ? ScalingMatrix( s[0].get<float>(), s[1].get<float>(), s[2].get<float>() ) : I;
				const Vector3 zc = e.type == ActorType::Zone ? Vector3( 0.95f, 0.8f, 0.3f ) : Vector3( 0.24f, 0.86f, 0.52f );
				Draw( m_meshes["wirebox"], S * T, sel ? selectCol : zc, false, true, e.type == ActorType::Zone ? 0.6f : 1.0f );
			}
			else if( e.type == ActorType::PointLight || e.type == ActorType::DirLight )
			{
				glPolygonMode( GL_FRONT_AND_BACK, GL_FILL );
				const Vector3 lc = sel ? selectCol : world::HexColor( e.props.value( "color", std::string( "#ffffff" ) ) );
				Draw( m_meshes["sphere"], ScalingMatrix( 0.5f, 0.5f, 0.5f ) * T, lc, false, true );
				if( e.type == ActorType::DirLight )
				{
					const Matrix R = RotationXMatrix( e.transform.rotation.x * kPi / 180 ) * RotationYMatrix( e.transform.rotation.y * kPi / 180 ) * RotationZMatrix( e.transform.rotation.z * kPi / 180 );
					Draw( m_meshes["cone"], ScalingMatrix( 0.3f, 1.2f, 0.3f ) * RotationXMatrix( kPi ) * TranslationMatrix( 0, -0.9f, 0 ) * R * T, lc, false, true );
				}
			}
			else
				Draw( m_meshes["wirebox"], ScalingMatrix( 0.6f, 0.6f, 0.6f ) * T, c, false, true );
			glPolygonMode( GL_FRONT_AND_BACK, f.mode == ViewMode::Wireframe ? GL_LINE : GL_FILL );
		}
		}
	}

	if( playing )
	{
		const auto* play = f.play;
		if( play->Possessed() && play->deadFor <= 0 )
		{
			const Matrix P = RotationYMatrix( play->PlayerYaw() ) * TranslationMatrix( play->PlayerPosition() );
			Draw( m_meshes["capsule"], TranslationMatrix( 0, 0.9f, 0 ) * P, Vector3( 0.23f, 0.44f, 0.84f ), false, false );
			Draw( m_meshes["cone"], ScalingMatrix( 0.24f, 0.35f, 0.24f ) * RotationXMatrix( -kPi / 2 ) * TranslationMatrix( 0, 1.45f, -0.38f ) * P, Vector3( 0.95f, 0.76f, 0.3f ), false, false );
		}
		for( size_t ci = 0; ci < play->Creatures().size(); ++ci )
		{
			const auto& c = play->Creatures()[ci];
			if( c.state == world::Creature::Dead ) continue;
			const Matrix C = RotationYMatrix( c.yaw ) * TranslationMatrix( c.position );
			Draw( m_meshes["capsule"], ScalingMatrix( 0.8f, 0.8f, 0.8f ) * RotationXMatrix( kPi / 2 ) * TranslationMatrix( 0, 0.5f, 0 ) * C, c.color, false, false );
			Draw( m_meshes["sphere"], ScalingMatrix( 0.55f, 0.55f, 0.55f ) * TranslationMatrix( 0, 0.75f, -0.7f ) * C, c.color * 1.1f, false, false );
			if( int( ci ) == play->target ) Draw( m_meshes["ring"], ScalingMatrix( 1.1f, 1, 1.1f ) * TranslationMatrix( 0, 0.08f, 0 ) * TranslationMatrix( c.position ), Vector3( 1, 0.25f, 0.2f ), false, true );
		}
	}

	// the selected actor's colliders (green: solid, cyan: trigger) - what Play will collide with
	if( !playing && f.selected && scene.Find( f.selected ) )
	{
		std::vector<world::Body> bodies;
		world::BodiesOf( scene, *scene.Find( f.selected ), bodies );
		glPolygonMode( GL_FRONT_AND_BACK, GL_FILL );
		for( const auto& b : bodies )
		{
			const Vector3 size = b.max - b.min, c = ( b.min + b.max ) * 0.5f;
			Draw( m_meshes["wirebox"], ScalingMatrix( std::max( size.x, 0.01f ), std::max( size.y, 0.01f ), std::max( size.z, 0.01f ) ) * TranslationMatrix( c ),
				  b.trigger ? Vector3( 0.3f, 0.85f, 0.95f ) : Vector3( 0.35f, 0.95f, 0.45f ), false, true );
		}
	}
	if( f.brushVisible && !playing )
	{
		glPolygonMode( GL_FRONT_AND_BACK, GL_FILL );
		glDisable( GL_DEPTH_TEST );
		Draw( m_meshes["ring"], ScalingMatrix( f.brushRadius, 1, f.brushRadius ) * TranslationMatrix( f.brushPos + Vector3( 0, 0.05f, 0 ) ), Vector3( 1, 0.83f, 0.3f ), false, true );
		Draw( m_meshes["ring"], ScalingMatrix( f.brushRadius * 0.5f, 1, f.brushRadius * 0.5f ) * TranslationMatrix( f.brushPos + Vector3( 0, 0.05f, 0 ) ), Vector3( 1, 0.83f, 0.3f ), false, true, 0.45f );
		glEnable( GL_DEPTH_TEST );
	}
	glPolygonMode( GL_FRONT_AND_BACK, GL_FILL );
	glBindVertexArray( 0 );
	glUseProgram( 0 );
	glBindFramebuffer( GL_FRAMEBUFFER, 0 );
}

std::vector<uint8_t> Renderer::ReadPixels() const
{
	std::vector<uint8_t> px( size_t( m_w * m_h * 4 ) ), out( px.size() );
	glBindFramebuffer( GL_FRAMEBUFFER, m_fbo );
	glPixelStorei( GL_PACK_ALIGNMENT, 1 );
	glReadPixels( 0, 0, m_w, m_h, GL_RGBA, GL_UNSIGNED_BYTE, px.data() );
	glBindFramebuffer( GL_FRAMEBUFFER, 0 );
	for( int y = 0; y < m_h; ++y ) std::copy_n( &px[size_t( ( m_h - 1 - y ) * m_w * 4 )], m_w * 4, &out[size_t( y * m_w * 4 )] );
	return out;
}
}
