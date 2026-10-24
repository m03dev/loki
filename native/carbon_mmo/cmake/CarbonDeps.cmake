# Fetches the third-party pieces this foundation needs. Everything is pinned.
include(FetchContent)
set(FETCHCONTENT_QUIET ON)

find_package(Python3 3.10 REQUIRED COMPONENTS Interpreter Development)

# --- DirectXMath (Carbon math dependency; header-only) -----------------------
FetchContent_Declare(directxmath
    GIT_REPOSITORY https://github.com/microsoft/DirectXMath.git
    GIT_TAG        apr2025
    GIT_SHALLOW    TRUE
    SOURCE_SUBDIR  _headers_only_)
FetchContent_MakeAvailable(directxmath)

add_library(cmmo_directxmath INTERFACE)
target_include_directories(cmmo_directxmath INTERFACE "${directxmath_SOURCE_DIR}/Inc")
if(NOT WIN32)
    # DirectXMath needs Microsoft's SAL annotations (sal.h); MSVC has it, Clang/GCC don't.
    target_include_directories(cmmo_directxmath INTERFACE "${CMAKE_SOURCE_DIR}/third_party/sal")
endif()

# --- Carbon math (carbonengine/math, MIT) ------------------------------------
if(CARBON_MATH_SOURCE_DIR)
    set(carbon_math_SOURCE_DIR "${CARBON_MATH_SOURCE_DIR}")
else()
    FetchContent_Declare(carbon_math
        GIT_REPOSITORY https://github.com/carbonengine/math.git
        GIT_TAG        e998264e693e0a2a6121627aed43ed584f2baa4d
        SOURCE_SUBDIR  _not_built_by_its_own_cmake_)
    FetchContent_MakeAvailable(carbon_math)
endif()

# --- pybind11 ----------------------------------------------------------------
FetchContent_Declare(pybind11
    GIT_REPOSITORY https://github.com/pybind/pybind11.git
    GIT_TAG        v3.1.0       # 2.13.x fails on the macOS 27 SDK (std::pointer_traits); 3.1 is fine
    GIT_SHALLOW    TRUE)
FetchContent_MakeAvailable(pybind11)

# --- nlohmann/json (level files, actor properties) ---------------------------
FetchContent_Declare(nlohmann_json
    GIT_REPOSITORY https://github.com/nlohmann/json.git
    GIT_TAG        v3.11.3
    GIT_SHALLOW    TRUE)
set(JSON_BuildTests OFF CACHE INTERNAL "")
FetchContent_MakeAvailable(nlohmann_json)

# --- Dear ImGui (docking) + ImGuizmo: the editor's UI ------------------------
if(CMMO_BUILD_EDITOR)
    FetchContent_Declare(imgui
        GIT_REPOSITORY https://github.com/ocornut/imgui.git
        GIT_TAG        v1.92.8-docking
        GIT_SHALLOW    TRUE
        SOURCE_SUBDIR  _no_cmake_)
    FetchContent_Declare(imguizmo
        GIT_REPOSITORY https://github.com/CedricGuillemet/ImGuizmo.git
        GIT_TAG        18cef5e031d8c6973d80284c67f60549fafd78c1
        SOURCE_SUBDIR  _no_cmake_)
    FetchContent_Declare(cgltf                     # glTF / glb loading for Model actors (MIT, one header)
        GIT_REPOSITORY https://github.com/jkuhlmann/cgltf.git
        GIT_TAG        v1.15
        GIT_SHALLOW    TRUE
        SOURCE_SUBDIR  _no_cmake_)
    FetchContent_MakeAvailable(imgui imguizmo cgltf)
endif()

# --- GLFW (optional windowed renderer) ---------------------------------------
if(CMMO_WITH_GLFW)
    set(GLFW_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
    set(GLFW_BUILD_TESTS OFF CACHE BOOL "" FORCE)
    set(GLFW_BUILD_DOCS OFF CACHE BOOL "" FORCE)
    set(GLFW_INSTALL OFF CACHE BOOL "" FORCE)
    set(GLFW_BUILD_WAYLAND OFF CACHE BOOL "" FORCE)
    FetchContent_Declare(glfw
        GIT_REPOSITORY https://github.com/glfw/glfw.git
        GIT_TAG        3.4
        GIT_SHALLOW    TRUE)
    FetchContent_MakeAvailable(glfw)
    find_package(OpenGL REQUIRED)
endif()
