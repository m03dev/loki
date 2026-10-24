// MODULE: editor.render
#include "editor/Renderer.h"

#include <algorithm>
#include <cmath>

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
  vec3 base = mix(uTint, vC * uTint, uVertexColor);
  if (uUnlit > 0.5) { frag = vec4(base, uAlpha); return; }
  vec3 n = normalize(vN);
  vec3 light = uAmbient + uSunColor * max(dot(n, -uSunDir), 0.0);
  for (int i = 0; i < uNumPoints; ++i) {
    vec3 d = uPointPos[i] - vW;
    float dist = length(d);
    float att = clamp(1.0 - dist / uPointRange[i], 0.0, 1.0);
    light += uPointCol[i] * max(dot(n, d / max(dist, 1e-4)), 0.0) * att * att;
  }
  vec3 c = base * light;
  float f = 1.0 - exp(-uFogDensity * length(vW - uEye));
  frag = vec4(mix(c, uFog, clamp(f, 0.0, 0.85)), uAlpha);
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
	glBufferData( GL_ARRAY_BUFFER, GLsizeiptr( verts.size() * sizeof( V ) ), verts.data(), GL_DYNAMIC_DRAW );
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
	glBindVertexArray( 0 );
	return m;
}

V Vert( float x, float y, float z, float nx, float ny, float nz )
{
	return V{ { x, y, z }, { nx, ny, nz }, { 1, 1, 1 } };
}

// unit primitives (about 1 m), centred on the origin unless noted
void Box( std::vector<V>& v, std::vector<uint32_t>& i )
{
	const float n[6][3] = { { 1, 0, 0 }, { -1, 0, 0 }, { 0, 1, 0 }, { 0, -1, 0 }, { 0, 0, 1 }, { 0, 0, -1 } };
	for( int f = 0; f < 6; ++f )
	{
		const float* N = n[f];
		// two axes perpendicular to the normal
		float u[3] = { N[1], N[2], N[0] }, w[3] = { N[1] * u[2] - N[2] * u[1], N[2] * u[0] - N[0] * u[2], N[0] * u[1] - N[1] * u[0] };
		const uint32_t b = uint32_t( v.size() );
		for( int k = 0; k < 4; ++k )
		{
			const float su = ( k == 1 || k == 2 ) ? 0.5f : -0.5f, sw = ( k >= 2 ) ? 0.5f : -0.5f;
			v.push_back( Vert( N[0] * 0.5f + u[0] * su + w[0] * sw, N[1] * 0.5f + u[1] * su + w[1] * sw, N[2] * 0.5f + u[2] * su + w[2] * sw,
							   N[0], N[1], N[2] ) );
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
			const float off = ny > 0 ? stretch : -stretch;   // capsule: push the two halves apart
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
	const float slope = ( rBot - rTop );
	for( int x = 0; x <= seg; ++x )
	{
		const float ph = 2 * kPi * x / seg, c = std::cos( ph ), s = std::sin( ph );
		const float len = std::sqrt( 1 + slope * slope );
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
void Grid( std::vector<V>& v, int half = 50, float step = 2.0f )
{
	for( int k = -half; k <= half; ++k )
	{
		const float shade = k == 0 ? 0.55f : ( k % 5 == 0 ? 0.38f : 0.26f );
		V a = Vert( k * step, 0, -half * step, 0, 1, 0 ), b = Vert( k * step, 0, half * step, 0, 1, 0 );
		V c = Vert( -half * step, 0, k * step, 0, 1, 0 ), d = Vert( half * step, 0, k * step, 0, 1, 0 );
		for( V* p : { &a, &b, &c, &d } ) p->c[0] = p->c[1] = p->c[2] = shade;
		v.insert( v.end(), { a, b, c, d } );
	}
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
	Matrix p( f / aspect, 0, 0, 0, 0, f, 0, 0, 0, 0, ( farZ + nearZ ) / ( nearZ - farZ ), -1, 0, 0, 2 * farZ * nearZ / ( nearZ - farZ ), 0 );
	return p;
}

void CameraView::Ray( float px, float py, float w, float h, Vector3& origin, Vector3& dir ) const
{
	const Matrix inv = Inverse( View() * Projection( w / std::max( 1.0f, h ) ) );
	const float nx = px / w * 2 - 1, ny = 1 - py / h * 2;
	const Vector3 a = TransformCoord( Vector3( nx, ny, -1 ), inv ), b = TransformCoord( Vector3( nx, ny, 1 ), inv );
	origin = a;
	dir = Normalize( b - a );
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
	u_eye = U( "uEye" ); u_fog = U( "uFog" ); u_fogDensity = U( "uFogDensity" );

	std::vector<V> v;
	std::vector<uint32_t> i;
	auto make = [&]( const char* name, unsigned prim ) { m_meshes[name] = Upload( v, i, prim ); v.clear(); i.clear(); };
	Box( v, i ); make( "cube", GL_TRIANGLES );
	Sphere( v, i ); make( "sphere", GL_TRIANGLES );
	Cylinder( v, i, 0.5f, 0.5f ); make( "cylinder", GL_TRIANGLES );
	Cylinder( v, i, 0.0f, 0.5f ); make( "cone", GL_TRIANGLES );
	Plane( v, i ); make( "plane", GL_TRIANGLES );
	Sphere( v, i, 0.35f, 16, 12, 0.0f, 0.55f ); make( "capsule", GL_TRIANGLES );   // 1.8 m tall, centred
	Ring( v ); make( "ring", GL_LINES );
	WireBox( v ); make( "wirebox", GL_LINES );
	Grid( v ); make( "grid", GL_LINES );
	return glGetError() == GL_NO_ERROR;
}

void Renderer::Shutdown()
{
	auto drop = []( Mesh& m ) {
		if( m.vao ) glDeleteVertexArrays( 1, &m.vao );
		if( m.vbo ) glDeleteBuffers( 1, &m.vbo );
		if( m.ibo ) glDeleteBuffers( 1, &m.ibo );
		m = Mesh();
	};
	for( auto& kv : m_meshes ) drop( kv.second );
	for( auto& kv : m_terrains ) drop( kv.second.mesh );
	m_meshes.clear();
	m_terrains.clear();
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
	if( g.mesh.vao && g.version == t.Version() && g.source == &t ) return g.mesh;
	const int res = t.Res(), n = res + 1;
	const float size = t.Size();
	std::vector<V> v( size_t( n * n ) );
	for( int j = 0; j < n; ++j )
		for( int i = 0; i < n; ++i )
		{
			const size_t k = size_t( j * n + i );
			const float x = ( float( i ) / res - 0.5f ) * size, z = ( float( j ) / res - 0.5f ) * size;
			const Vector3 nr = t.NormalAt( x, z );
			v[k] = V{ { x, t.Heights()[k], z }, { nr.x, nr.y, nr.z },
					  { t.Colors()[k * 3] / 255.0f, t.Colors()[k * 3 + 1] / 255.0f, t.Colors()[k * 3 + 2] / 255.0f } };
		}
	if( g.mesh.vao && g.source == &t && g.mesh.count == res * res * 6 )
	{
		glBindBuffer( GL_ARRAY_BUFFER, g.mesh.vbo );
		glBufferSubData( GL_ARRAY_BUFFER, 0, GLsizeiptr( v.size() * sizeof( V ) ), v.data() );
	}
	else
	{
		if( g.mesh.vao )
		{
			glDeleteVertexArrays( 1, &g.mesh.vao );
			glDeleteBuffers( 1, &g.mesh.vbo );
			glDeleteBuffers( 1, &g.mesh.ibo );
		}
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
	g.source = &t;
	return g.mesh;
}

void Renderer::Draw( const Mesh& mesh, const Matrix& world, const Vector3& tint, bool vertexColor, bool unlit, float alpha )
{
	const Matrix mvp = world * m_viewProj;
	glUniformMatrix4fv( u_mvp, 1, GL_FALSE, &mvp._11 );   // Carbon row-major + row vectors = GL column-major memory
	glUniformMatrix4fv( u_model, 1, GL_FALSE, &world._11 );
	glUniform3f( u_tint, tint.x, tint.y, tint.z );
	glUniform1f( u_vcol, vertexColor ? 1.0f : 0.0f );
	glUniform1f( u_unlit, unlit ? 1.0f : 0.0f );
	glUniform1f( u_alpha, alpha );
	glBindVertexArray( mesh.vao );
	if( mesh.ibo ) glDrawElements( mesh.prim, mesh.count, GL_UNSIGNED_INT, nullptr );
	else glDrawArrays( mesh.prim, 0, mesh.count );
	++m_drawCalls;
}

void Renderer::Render( int width, int height, const FrameInfo& f )
{
	EnsureTarget( width, height );
	m_drawCalls = 0;
	glBindFramebuffer( GL_FRAMEBUFFER, m_fbo );
	glViewport( 0, 0, m_w, m_h );
	glClearColor( f.clear.x, f.clear.y, f.clear.z, 1 );
	glClear( GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT );
	glEnable( GL_DEPTH_TEST );
	glDisable( GL_CULL_FACE );
	glEnable( GL_BLEND );
	glBlendFunc( GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA );
	if( !f.scene )
	{
		glBindFramebuffer( GL_FRAMEBUFFER, 0 );
		return;
	}
	const world::Scene& scene = f.play ? f.play->World() : *f.scene;
	const bool playing = f.play != nullptr;
	m_viewProj = f.camera.View() * f.camera.Projection( float( m_w ) / float( m_h ) );
	glUseProgram( m_program );

	// lights: the first visible Sun (else a default one) + up to 8 point lights
	Vector3 sunDir = Normalize( Vector3( -0.4f, -1.0f, -0.3f ) ), sunCol( 1.0f, 0.96f, 0.88f );
	float px[24], pc[24], pr[8];
	int np = 0;
	bool haveSun = false;
	for( const auto& e : scene.Entities() )
	{
		if( !e.visible ) continue;
		if( e.type == ActorType::DirLight && !haveSun )
		{
			sunDir = Normalize( TransformNormal( Vector3( 0, -1, 0 ), e.transform.World() ) );
			sunCol = world::HexColor( e.props.value( "color", std::string( "#fff4e0" ) ) ) * e.props.value( "intensity", 1.0f );
			haveSun = true;
		}
		if( e.type == ActorType::PointLight && np < 8 )
		{
			const Vector3 c = world::HexColor( e.props.value( "color", std::string( "#ffd9a0" ) ) ) * e.props.value( "intensity", 2.0f );
			px[np * 3] = e.transform.position.x; px[np * 3 + 1] = e.transform.position.y; px[np * 3 + 2] = e.transform.position.z;
			pc[np * 3] = c.x; pc[np * 3 + 1] = c.y; pc[np * 3 + 2] = c.z;
			pr[np] = std::max( 0.1f, e.props.value( "range", 15.0f ) );
			++np;
		}
	}
	glUniform3f( u_sunDir, sunDir.x, sunDir.y, sunDir.z );
	glUniform3f( u_sunCol, sunCol.x, sunCol.y, sunCol.z );
	glUniform3f( u_ambient, 0.32f, 0.36f, 0.42f );
	glUniform1i( u_nPoints, np );
	if( np )
	{
		glUniform3fv( u_pointPos, np, px );
		glUniform3fv( u_pointCol, np, pc );
		glUniform1fv( u_pointRange, np, pr );
	}
	glUniform3f( u_eye, f.camera.eye.x, f.camera.eye.y, f.camera.eye.z );
	glUniform3f( u_fog, f.clear.x, f.clear.y, f.clear.z );
	glUniform1f( u_fogDensity, playing ? 0.006f : 0.002f );

	const Matrix I = IdentityMatrix();
	if( f.grid && !playing ) Draw( m_meshes["grid"], TranslationMatrix( 0, -0.05f, 0 ), Vector3( 1, 1, 1 ), true, true, 0.8f );   // under the terrain

	const Vector3 selectCol( 1.0f, 0.62f, 0.15f );
	for( const auto& e : scene.Entities() )
	{
		if( !e.visible ) continue;
		const bool sel = !playing && e.id == f.selected;
		const Matrix W = e.transform.World();
		const Matrix T = TranslationMatrix( e.transform.position );   // markers ignore scale
		switch( e.type )
		{
		case ActorType::Terrain:
		{
			if( !e.terrain ) break;
			const Mesh& tm = TerrainMesh( e );
			Draw( tm, T, Vector3( 1, 1, 1 ), true, false );
			if( sel )
			{
				glPolygonMode( GL_FRONT_AND_BACK, GL_LINE );
				glEnable( GL_POLYGON_OFFSET_LINE );
				glPolygonOffset( -1, -1 );
				Draw( tm, T, selectCol, false, true, 0.25f );
				glDisable( GL_POLYGON_OFFSET_LINE );
				glPolygonMode( GL_FRONT_AND_BACK, GL_FILL );
			}
			break;
		}
		case ActorType::Mesh:
		{
			std::string shape = e.props.value( "shape", std::string( "cube" ) );
			if( !m_meshes.count( shape ) || shape == "ring" || shape == "grid" || shape == "wirebox" || shape == "capsule" ) shape = "cube";
			const Matrix lift = shape == "plane" ? I : TranslationMatrix( 0, 0.5f, 0 );   // shapes sit on their pivot
			Draw( m_meshes[shape], lift * W, world::HexColor( e.props.value( "color", std::string( "#b8b2a6" ) ) ), false, false );
			if( sel )
			{
				glPolygonMode( GL_FRONT_AND_BACK, GL_LINE );
				Draw( m_meshes[shape], ScalingMatrix( 1.02f, 1.02f, 1.02f ) * lift * W, selectCol, false, true );
				glPolygonMode( GL_FRONT_AND_BACK, GL_FILL );
			}
			break;
		}
		default:
		{
			if( playing ) break;   // editor markers are hidden while playing
			const Vector3 c = sel ? selectCol : Vector3( 0.3f, 0.65f, 1.0f );
			if( e.type == ActorType::PlayerStart )
			{
				glPolygonMode( GL_FRONT_AND_BACK, GL_LINE );
				Draw( m_meshes["capsule"], TranslationMatrix( 0, 0.9f, 0 ) * RotationYMatrix( e.transform.rotation.y * kPi / 180 ) * T, c, false, true );
				glPolygonMode( GL_FRONT_AND_BACK, GL_FILL );
				Draw( m_meshes["cone"], ScalingMatrix( 0.25f, 0.5f, 0.25f ) * RotationXMatrix( -kPi / 2 ) * TranslationMatrix( 0, 1.5f, -0.5f ) *
											RotationYMatrix( e.transform.rotation.y * kPi / 180 ) * T, c, false, true );
			}
			else if( e.type == ActorType::CreatureSpawn )
			{
				const Vector3 col = sel ? selectCol : world::HexColor( e.props.value( "color", std::string( "#b5452f" ) ) );
				const float r = e.props.value( "wander", 6.0f );
				Draw( m_meshes["ring"], ScalingMatrix( r, 1, r ) * TranslationMatrix( 0, 0.1f, 0 ) * T, col, false, true );
				Draw( m_meshes["cone"], ScalingMatrix( 0.5f, 0.8f, 0.5f ) * RotationXMatrix( kPi ) * TranslationMatrix( 0, 1.2f, 0 ) * T, col, false, true );
			}
			else if( e.type == ActorType::TriggerBox )
			{
				const auto& s = e.props["size"];
				const Matrix S = s.is_array() && s.size() == 3 ? ScalingMatrix( s[0].get<float>(), s[1].get<float>(), s[2].get<float>() ) : I;
				Draw( m_meshes["wirebox"], S * T, sel ? selectCol : Vector3( 0.24f, 0.86f, 0.52f ), false, true );
			}
			else if( e.type == ActorType::PointLight || e.type == ActorType::DirLight )
			{
				const Vector3 lc = sel ? selectCol : world::HexColor( e.props.value( "color", std::string( "#ffffff" ) ) );
				Draw( m_meshes["sphere"], ScalingMatrix( 0.5f, 0.5f, 0.5f ) * T, lc, false, true );
				if( e.type == ActorType::DirLight )
					Draw( m_meshes["cone"], ScalingMatrix( 0.3f, 1.2f, 0.3f ) * RotationXMatrix( kPi ) * TranslationMatrix( 0, -0.9f, 0 ) *
												RotationXMatrix( e.transform.rotation.x * kPi / 180 ) * RotationYMatrix( e.transform.rotation.y * kPi / 180 ) *
												RotationZMatrix( e.transform.rotation.z * kPi / 180 ) * T, lc, false, true );
			}
			else
				Draw( m_meshes["wirebox"], ScalingMatrix( 0.5f, 0.5f, 0.5f ) * T, c, false, true );
		}
		}
	}

	if( playing )
	{
		const auto* play = f.play;
		if( play->Possessed() )
		{
			const Matrix P = RotationYMatrix( play->PlayerYaw() ) * TranslationMatrix( play->PlayerPosition() );
			Draw( m_meshes["capsule"], TranslationMatrix( 0, 0.9f, 0 ) * P, Vector3( 0.23f, 0.44f, 0.84f ), false, false );
			Draw( m_meshes["cone"], ScalingMatrix( 0.24f, 0.35f, 0.24f ) * RotationXMatrix( -kPi / 2 ) * TranslationMatrix( 0, 1.45f, -0.38f ) * P,
				  Vector3( 0.95f, 0.76f, 0.3f ), false, false );
		}
		for( const auto& c : play->Creatures() )
		{
			const Matrix C = RotationYMatrix( c.yaw ) * TranslationMatrix( c.position );
			Draw( m_meshes["capsule"], ScalingMatrix( 0.8f, 0.8f, 0.8f ) * RotationXMatrix( kPi / 2 ) * TranslationMatrix( 0, 0.5f, 0 ) * C, c.color, false, false );
			Draw( m_meshes["sphere"], ScalingMatrix( 0.55f, 0.55f, 0.55f ) * TranslationMatrix( 0, 0.75f, -0.7f ) * C, c.color, false, false );
			if( c.state == world::Creature::Chase )
				Draw( m_meshes["cone"], ScalingMatrix( 0.2f, 0.3f, 0.2f ) * RotationXMatrix( kPi ) * TranslationMatrix( 0, 1.7f, 0 ) * C,
					  Vector3( 1, 0.15f, 0.1f ), false, true );   // red marker over an attacking creature
		}
	}

	if( f.brushVisible && !playing )
	{
		glDisable( GL_DEPTH_TEST );
		Draw( m_meshes["ring"], ScalingMatrix( f.brushRadius, 1, f.brushRadius ) * TranslationMatrix( f.brushPos + Vector3( 0, 0.05f, 0 ) ),
			  Vector3( 1, 0.83f, 0.3f ), false, true );
		glEnable( GL_DEPTH_TEST );
	}
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
