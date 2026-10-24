// MODULE: editor.gl
// The OpenGL 3.3 core functions the editor's renderer uses, loaded at runtime from whatever made the context
// (GLFW on macOS / Windows, EGL for the headless build). One list, no generator.
#pragma once

#include <GL/glcorearb.h>

#define CMMO_GL_FUNCS( X )                                                                                   \
	X( PFNGLCLEARPROC, glClear )                                                                             \
	X( PFNGLCLEARCOLORPROC, glClearColor )                                                                   \
	X( PFNGLVIEWPORTPROC, glViewport )                                                                       \
	X( PFNGLENABLEPROC, glEnable )                                                                           \
	X( PFNGLDISABLEPROC, glDisable )                                                                         \
	X( PFNGLDEPTHMASKPROC, glDepthMask )                                                                     \
	X( PFNGLBLENDFUNCPROC, glBlendFunc )                                                                     \
	X( PFNGLLINEWIDTHPROC, glLineWidth )                                                                     \
	X( PFNGLPOLYGONMODEPROC, glPolygonMode )                                                                 \
	X( PFNGLPOLYGONOFFSETPROC, glPolygonOffset )                                                             \
	X( PFNGLGETERRORPROC, glGetError )                                                                       \
	X( PFNGLGETSTRINGPROC, glGetString )                                                                     \
	X( PFNGLREADPIXELSPROC, glReadPixels )                                                                   \
	X( PFNGLPIXELSTOREIPROC, glPixelStorei )                                                                 \
	X( PFNGLGENBUFFERSPROC, glGenBuffers )                                                                   \
	X( PFNGLDELETEBUFFERSPROC, glDeleteBuffers )                                                             \
	X( PFNGLBINDBUFFERPROC, glBindBuffer )                                                                   \
	X( PFNGLBUFFERDATAPROC, glBufferData )                                                                   \
	X( PFNGLBUFFERSUBDATAPROC, glBufferSubData )                                                             \
	X( PFNGLGENVERTEXARRAYSPROC, glGenVertexArrays )                                                         \
	X( PFNGLDELETEVERTEXARRAYSPROC, glDeleteVertexArrays )                                                   \
	X( PFNGLBINDVERTEXARRAYPROC, glBindVertexArray )                                                         \
	X( PFNGLENABLEVERTEXATTRIBARRAYPROC, glEnableVertexAttribArray )                                         \
	X( PFNGLVERTEXATTRIBPOINTERPROC, glVertexAttribPointer )                                                 \
	X( PFNGLVERTEXATTRIB3FPROC, glVertexAttrib3f )                                                           \
	X( PFNGLDISABLEVERTEXATTRIBARRAYPROC, glDisableVertexAttribArray )                                       \
	X( PFNGLDRAWARRAYSPROC, glDrawArrays )                                                                   \
	X( PFNGLDRAWELEMENTSPROC, glDrawElements )                                                               \
	X( PFNGLCREATESHADERPROC, glCreateShader )                                                               \
	X( PFNGLSHADERSOURCEPROC, glShaderSource )                                                               \
	X( PFNGLCOMPILESHADERPROC, glCompileShader )                                                             \
	X( PFNGLGETSHADERIVPROC, glGetShaderiv )                                                                 \
	X( PFNGLGETSHADERINFOLOGPROC, glGetShaderInfoLog )                                                       \
	X( PFNGLDELETESHADERPROC, glDeleteShader )                                                               \
	X( PFNGLCREATEPROGRAMPROC, glCreateProgram )                                                             \
	X( PFNGLATTACHSHADERPROC, glAttachShader )                                                               \
	X( PFNGLBINDATTRIBLOCATIONPROC, glBindAttribLocation )                                                   \
	X( PFNGLLINKPROGRAMPROC, glLinkProgram )                                                                 \
	X( PFNGLGETPROGRAMIVPROC, glGetProgramiv )                                                               \
	X( PFNGLGETPROGRAMINFOLOGPROC, glGetProgramInfoLog )                                                     \
	X( PFNGLUSEPROGRAMPROC, glUseProgram )                                                                   \
	X( PFNGLDELETEPROGRAMPROC, glDeleteProgram )                                                             \
	X( PFNGLGETUNIFORMLOCATIONPROC, glGetUniformLocation )                                                   \
	X( PFNGLUNIFORMMATRIX4FVPROC, glUniformMatrix4fv )                                                       \
	X( PFNGLUNIFORM3FPROC, glUniform3f )                                                                     \
	X( PFNGLUNIFORM3FVPROC, glUniform3fv )                                                                   \
	X( PFNGLUNIFORM1FPROC, glUniform1f )                                                                     \
	X( PFNGLUNIFORM1FVPROC, glUniform1fv )                                                                   \
	X( PFNGLUNIFORM1IPROC, glUniform1i )                                                                     \
	X( PFNGLGENTEXTURESPROC, glGenTextures )                                                                 \
	X( PFNGLDELETETEXTURESPROC, glDeleteTextures )                                                           \
	X( PFNGLBINDTEXTUREPROC, glBindTexture )                                                                 \
	X( PFNGLTEXIMAGE2DPROC, glTexImage2D )                                                                   \
	X( PFNGLTEXPARAMETERIPROC, glTexParameteri )                                                             \
	X( PFNGLGENFRAMEBUFFERSPROC, glGenFramebuffers )                                                         \
	X( PFNGLDELETEFRAMEBUFFERSPROC, glDeleteFramebuffers )                                                   \
	X( PFNGLBINDFRAMEBUFFERPROC, glBindFramebuffer )                                                         \
	X( PFNGLFRAMEBUFFERTEXTURE2DPROC, glFramebufferTexture2D )                                               \
	X( PFNGLGENRENDERBUFFERSPROC, glGenRenderbuffers )                                                       \
	X( PFNGLDELETERENDERBUFFERSPROC, glDeleteRenderbuffers )                                                 \
	X( PFNGLBINDRENDERBUFFERPROC, glBindRenderbuffer )                                                       \
	X( PFNGLRENDERBUFFERSTORAGEPROC, glRenderbufferStorage )                                                 \
	X( PFNGLFRAMEBUFFERRENDERBUFFERPROC, glFramebufferRenderbuffer )                                         \
	X( PFNGLCHECKFRAMEBUFFERSTATUSPROC, glCheckFramebufferStatus )

namespace cmmo::gl
{
#define CMMO_GL_DECLARE( type, name ) extern type name;
CMMO_GL_FUNCS( CMMO_GL_DECLARE )
#undef CMMO_GL_DECLARE

using GetProc = void* ( * )( const char* name );
// Loads every function above. Returns the name of the first one missing, or nullptr when all loaded.
const char* Load( GetProc getProc );
}

// the renderer writes plain glFoo(...): route those names to the loaded pointers
#define CMMO_GL_ROUTE( type, name ) using cmmo::gl::name;
