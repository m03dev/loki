// MODULE: editor.gl
#include "editor/GL.h"

namespace cmmo::gl
{
#define CMMO_GL_DEFINE( type, name ) type name = nullptr;
CMMO_GL_FUNCS( CMMO_GL_DEFINE )
#undef CMMO_GL_DEFINE

const char* Load( GetProc getProc )
{
#define CMMO_GL_LOAD( type, name )                                   \
	name = reinterpret_cast<type>( getProc( #name ) );               \
	if( !name ) return #name;
	CMMO_GL_FUNCS( CMMO_GL_LOAD )
#undef CMMO_GL_LOAD
	return nullptr;
}
}
