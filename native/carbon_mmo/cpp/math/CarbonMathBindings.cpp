// MODULE: math
#include "math/CarbonMathBindings.h"

#include <pybind11/operators.h>

#include <cstring>
#include <sstream>
#include <string>

#include "Vector3.h" // Carbon math

namespace py = pybind11;

namespace
{
constexpr size_t kPackedSize = 3 * sizeof( float ); // wire format: 3 x float32, little endian

py::bytes Pack( const Vector3& v )
{
	char buffer[kPackedSize];
	std::memcpy( buffer, &v.x, sizeof( float ) );
	std::memcpy( buffer + 4, &v.y, sizeof( float ) );
	std::memcpy( buffer + 8, &v.z, sizeof( float ) );
	return py::bytes( buffer, kPackedSize );
}

Vector3 Unpack( const py::bytes& data )
{
	std::string raw = data;
	if( raw.size() != kPackedSize )
	{
		throw py::value_error( "Vector3.unpack expects exactly 12 bytes" );
	}
	Vector3 v;
	std::memcpy( &v.x, raw.data(), sizeof( float ) );
	std::memcpy( &v.y, raw.data() + 4, sizeof( float ) );
	std::memcpy( &v.z, raw.data() + 8, sizeof( float ) );
	return v;
}

// Moves `from` toward `to` by at most `max_step`; built on Carbon's ClampLength.
Vector3 MoveTowards( const Vector3& from, const Vector3& to, float max_step )
{
	return from + ClampLength( to - from, max_step );
}
}

namespace cmmo
{
void BindCarbonMath( py::module_& m )
{
	py::class_<Vector3>( m, "Vector3", py::module_local(), "Carbon math Vector3 (float32 x/y/z)" )
		.def( py::init<>() )
		.def( py::init<float, float, float>(), py::arg( "x" ), py::arg( "y" ), py::arg( "z" ) )
		.def_readwrite( "x", &Vector3::x )
		.def_readwrite( "y", &Vector3::y )
		.def_readwrite( "z", &Vector3::z )
		.def( py::self + py::self )
		.def( py::self - py::self )
		.def( py::self * float() )
		.def( float() * py::self )
		.def( py::self / float() )
		.def( -py::self )
		.def( py::self == py::self )
		.def( py::self != py::self )
		.def( "length", []( const Vector3& v ) { return Length( v ); } )
		.def( "length_sq", []( const Vector3& v ) { return LengthSq( v ); } )
		.def( "normalized", []( const Vector3& v ) { return Normalize( v ); } )
		.def( "dot", []( const Vector3& a, const Vector3& b ) { return Dot( a, b ); } )
		.def( "cross", []( const Vector3& a, const Vector3& b ) { return Cross( a, b ); } )
		.def( "distance", []( const Vector3& a, const Vector3& b ) { return Length( a - b ); } )
		.def( "lerp", []( const Vector3& a, const Vector3& b, float s ) { return Lerp( a, b, s ); } )
		.def( "move_towards", &MoveTowards, py::arg( "target" ), py::arg( "max_step" ) )
		.def( "to_tuple", []( const Vector3& v ) { return py::make_tuple( v.x, v.y, v.z ); } )
		.def( "pack", &Pack, "12-byte little-endian float32 encoding for the network layer" )
		.def_static( "unpack", &Unpack )
		.def( "__repr__",
			  []( const Vector3& v ) {
				  std::ostringstream s;
				  s << "Vector3(" << v.x << ", " << v.y << ", " << v.z << ")";
				  return s.str();
			  } )
		.def( py::pickle( []( const Vector3& v ) { return py::make_tuple( v.x, v.y, v.z ); },
						  []( py::tuple t ) { return Vector3( t[0].cast<float>(), t[1].cast<float>(), t[2].cast<float>() ); } ) );

	m.attr( "PACKED_SIZE" ) = kPackedSize;
	m.attr( "BACKEND" ) = "carbon-math (carbonengine/math + DirectXMath)";
}
}
