# Carbon MMO Foundation - code-driven, modular MMO engine base on top of the
# open-source Carbon framework (github.com/carbonengine).
#
# What this CMake project builds (all of it compiles without CCP's vcpkg registry):
#   CarbonMath   - static lib, Carbon's math sources (carbonengine/math) + DirectXMath
#   cmmo_math    - Python extension exposing Carbon Vector3 to Python   (MODULE: math)
#   cmmo_host    - C++ host that embeds Python and runs the render hook (MODULE: script-host, render)
#
# The heavier Carbon modules (Blue, CarbonIO, Scheduler, Destiny) are built with
# their own repos + CCP's vcpkg registry and are picked up at *runtime* by the
# Python adapter layers. See README.md, "Full Carbon stack".

cmake_minimum_required(VERSION 3.24)
project(CarbonMMO VERSION 0.1.0 LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

if(APPLE OR WIN32)
    set(_cmmo_glfw_default ON)
else()
    set(_cmmo_glfw_default OFF)
endif()
option(CMMO_WITH_GLFW "Build the windowed GLFW/OpenGL renderer backend (null renderer is always built)" ${_cmmo_glfw_default})
set(CARBON_MATH_SOURCE_DIR "" CACHE PATH "Use a local carbonengine/math checkout instead of fetching it")
option(CMMO_BUILD_EDITOR "Build the engine editor (cmmo_editor)" ON)
if(NOT CMMO_WITH_GLFW AND UNIX AND NOT APPLE)
    set(CMMO_EDITOR_EGL ON)    # Linux without a window system build: the editor runs headless (EGL, self-test)
endif()

include(cmake/CarbonDeps.cmake)

# ---------------------------------------------------------------------------
# MODULE: math - Carbon math (vendored by fetch, compiled as-is, no patches)
# ---------------------------------------------------------------------------
file(GLOB CARBON_MATH_SOURCES CONFIGURE_DEPENDS "${carbon_math_SOURCE_DIR}/src/*.cpp")
# macOS writes "._Name.cpp" metadata files next to every file on exFAT / FAT drives (e.g. an external build drive).
# They are not C++: never compile them.
list(FILTER CARBON_MATH_SOURCES EXCLUDE REGEX "/\\._[^/]*$")
list(LENGTH CARBON_MATH_SOURCES _n_math)
if(NOT _n_math EQUAL 10)
    message(WARNING "Carbon math: expected 10 source files, found ${_n_math}: ${CARBON_MATH_SOURCES}")
endif()
add_library(CarbonMath STATIC ${CARBON_MATH_SOURCES})
target_include_directories(CarbonMath PUBLIC "${carbon_math_SOURCE_DIR}/include")
target_link_libraries(CarbonMath PUBLIC cmmo_directxmath)
if(MSVC)
    target_compile_options(CarbonMath PRIVATE /W3 /wd4244)
else()
    target_compile_options(CarbonMath PRIVATE -w)
endif()

# Shared binding code (used by both the extension and the embedded host module)
add_library(cmmo_math_bindings STATIC cpp/math/CarbonMathBindings.cpp)
target_include_directories(cmmo_math_bindings PUBLIC cpp)
target_link_libraries(cmmo_math_bindings PUBLIC CarbonMath pybind11::headers Python3::Module)

pybind11_add_module(cmmo_math MODULE cpp/math/cmmo_math_module.cpp)
target_link_libraries(cmmo_math PRIVATE cmmo_math_bindings)
# Put the extension in one predictable folder on every generator (no Debug/Release subdir).
set_target_properties(cmmo_math PROPERTIES
    LIBRARY_OUTPUT_DIRECTORY "$<1:${CMAKE_BINARY_DIR}/python>"
    RUNTIME_OUTPUT_DIRECTORY "$<1:${CMAKE_BINARY_DIR}/python>")

# ---------------------------------------------------------------------------
# MODULE: world - scene, terrain, Play simulation, level files (no graphics)
# ---------------------------------------------------------------------------
add_library(cmmo_world STATIC cpp/world/World.cpp)
target_include_directories(cmmo_world PUBLIC cpp)
target_link_libraries(cmmo_world PUBLIC CarbonMath nlohmann_json::nlohmann_json)
add_executable(test_world tests/cpp/test_world.cpp)
target_link_libraries(test_world PRIVATE cmmo_world)
set_target_properties(test_world PROPERTIES RUNTIME_OUTPUT_DIRECTORY "$<1:${CMAKE_BINARY_DIR}/bin>")

# ---------------------------------------------------------------------------
# MODULE: render - renderer interface + backends
# ---------------------------------------------------------------------------
add_library(cmmo_render STATIC
    cpp/render/RenderConfig.cpp
    cpp/render/NullRenderer.cpp
    cpp/render/RendererFactory.cpp)
target_include_directories(cmmo_render PUBLIC cpp)
if(CMMO_WITH_GLFW)
    target_sources(cmmo_render PRIVATE cpp/render/GlfwRenderer.cpp)
    target_compile_definitions(cmmo_render PUBLIC CMMO_WITH_GLFW=1)
    target_link_libraries(cmmo_render PUBLIC glfw OpenGL::GL)
endif()

# ---------------------------------------------------------------------------
# MODULE: script-host - embedded Python + C++ <-> Python binding pipeline
# ---------------------------------------------------------------------------
add_executable(cmmo_host
    cpp/script_host/ScriptHost.cpp
    cpp/script_host/EngineModule.cpp
    cpp/apps/cmmo_host.cpp)
target_link_libraries(cmmo_host PRIVATE cmmo_render cmmo_math_bindings pybind11::embed)
execute_process(
    COMMAND "${Python3_EXECUTABLE}" -c "import sys; print(sys.base_prefix, end='')"
    OUTPUT_VARIABLE CMMO_PYTHON_HOME)
file(TO_CMAKE_PATH "${CMMO_PYTHON_HOME}" CMMO_PYTHON_HOME)
target_compile_definitions(cmmo_host PRIVATE
    CMMO_PYTHON_HOME="${CMMO_PYTHON_HOME}"
    CMMO_SOURCE_DIR="${CMAKE_SOURCE_DIR}"
    CMMO_BINARY_DIR="${CMAKE_BINARY_DIR}")
set_target_properties(cmmo_host PROPERTIES RUNTIME_OUTPUT_DIRECTORY "$<1:${CMAKE_BINARY_DIR}/bin>")

if(WIN32)
    # The embedded interpreter needs python3XX.dll next to the exe.
    file(GLOB _py_dlls "${Python3_RUNTIME_LIBRARY_DIRS}/python3*.dll" "${CMMO_PYTHON_HOME}/python3*.dll")
    foreach(_dll IN LISTS _py_dlls)
        add_custom_command(TARGET cmmo_host POST_BUILD
            COMMAND ${CMAKE_COMMAND} -E copy_if_different "${_dll}" "$<TARGET_FILE_DIR:cmmo_host>")
    endforeach()
endif()

# ---------------------------------------------------------------------------
# MODULE: editor - the engine editor (Dear ImGui docking + ImGuizmo + editor.render)
# ---------------------------------------------------------------------------
if(CMMO_BUILD_EDITOR AND (CMMO_WITH_GLFW OR CMMO_EDITOR_EGL))
    add_library(cmmo_imgui STATIC
        ${imgui_SOURCE_DIR}/imgui.cpp ${imgui_SOURCE_DIR}/imgui_draw.cpp ${imgui_SOURCE_DIR}/imgui_tables.cpp
        ${imgui_SOURCE_DIR}/imgui_widgets.cpp ${imgui_SOURCE_DIR}/imgui_demo.cpp
        ${imgui_SOURCE_DIR}/backends/imgui_impl_opengl3.cpp
        ${imguizmo_SOURCE_DIR}/src/ImGuizmo.cpp)
    target_include_directories(cmmo_imgui PUBLIC ${imgui_SOURCE_DIR} ${imgui_SOURCE_DIR}/backends ${imguizmo_SOURCE_DIR}/src)
    if(CMMO_WITH_GLFW)
        target_sources(cmmo_imgui PRIVATE ${imgui_SOURCE_DIR}/backends/imgui_impl_glfw.cpp)
        target_link_libraries(cmmo_imgui PUBLIC glfw)
    endif()
    if(NOT MSVC)
        target_compile_options(cmmo_imgui PRIVATE -w)
    endif()
    if(UNIX AND NOT APPLE)
        target_link_libraries(cmmo_imgui PUBLIC ${CMAKE_DL_LIBS})
    endif()

    add_library(cmmo_editor_lib STATIC cpp/editor/GL.cpp cpp/editor/Renderer.cpp cpp/editor/Theme.cpp cpp/editor/Editor.cpp)
    target_include_directories(cmmo_editor_lib PUBLIC cpp ${CMAKE_SOURCE_DIR}/third_party/khronos ${CMAKE_SOURCE_DIR}/third_party/fonts ${cgltf_SOURCE_DIR})
    target_compile_definitions(cmmo_editor_lib PRIVATE CMMO_SOURCE_DIR="${CMAKE_SOURCE_DIR}")
    target_link_libraries(cmmo_editor_lib PUBLIC cmmo_world cmmo_imgui)

    option(CMMO_EDITOR_PYTHON "Embed Python in the editor (the Phase 1 init hook). OFF = a portable editor with no Python dependency" ON)
    if(CMMO_EDITOR_PYTHON)
        add_executable(cmmo_editor cpp/apps/cmmo_editor.cpp cpp/script_host/ScriptHost.cpp cpp/script_host/EngineModule.cpp)
        target_link_libraries(cmmo_editor PRIVATE cmmo_editor_lib cmmo_render cmmo_math_bindings pybind11::embed)
        target_compile_definitions(cmmo_editor PRIVATE CMMO_EDITOR_PYTHON=1)
    else()
        add_executable(cmmo_editor cpp/apps/cmmo_editor.cpp)
        target_link_libraries(cmmo_editor PRIVATE cmmo_editor_lib)
        target_compile_definitions(cmmo_editor PRIVATE CMMO_EDITOR_PYTHON=0)
    endif()
    target_compile_definitions(cmmo_editor PRIVATE
        CMMO_PYTHON_HOME="${CMMO_PYTHON_HOME}" CMMO_SOURCE_DIR="${CMAKE_SOURCE_DIR}" CMMO_BINARY_DIR="${CMAKE_BINARY_DIR}")
    if(CMMO_WITH_GLFW)
        target_compile_definitions(cmmo_editor PRIVATE CMMO_WITH_GLFW=1)
    else()
        target_compile_definitions(cmmo_editor PRIVATE CMMO_WITH_EGL=1)
    endif()
    set_target_properties(cmmo_editor PROPERTIES RUNTIME_OUTPUT_DIRECTORY "$<1:${CMAKE_BINARY_DIR}/bin>")
    if(APPLE)
        target_compile_definitions(cmmo_editor_lib PUBLIC GL_SILENCE_DEPRECATION)
        target_link_libraries(cmmo_editor PRIVATE objc)   # BringToFront(): the window opens in front
    endif()
    if(WIN32)
        target_compile_definitions(cmmo_editor_lib PUBLIC NOMINMAX WIN32_LEAN_AND_MEAN)   # windows.h (via glcorearb.h) vs std::max
    endif()
    if(WIN32)
        foreach(_dll IN LISTS _py_dlls)
            add_custom_command(TARGET cmmo_editor POST_BUILD
                COMMAND ${CMAKE_COMMAND} -E copy_if_different "${_dll}" "$<TARGET_FILE_DIR:cmmo_editor>")
        endforeach()
    endif()
endif()

# ---------------------------------------------------------------------------
# Tests: `ctest --test-dir build -C Release --output-on-failure`
# ---------------------------------------------------------------------------
enable_testing()
add_test(NAME phase1_host COMMAND cmmo_host)
add_test(NAME world COMMAND test_world)
foreach(_t phase2_net phase3_click_to_move carbon_contracts)
    add_test(NAME ${_t} COMMAND "${Python3_EXECUTABLE}" "${CMAKE_SOURCE_DIR}/tests/test_${_t}.py")
    set_tests_properties(${_t} PROPERTIES ENVIRONMENT "CMMO_BUILD_DIR=${CMAKE_BINARY_DIR}" TIMEOUT 60)
endforeach()
set_tests_properties(phase1_host PROPERTIES TIMEOUT 60)

message(STATUS "Carbon MMO: Python ${Python3_VERSION} (${Python3_EXECUTABLE})")
# run_tests.py re-runs itself with this interpreter: the extension only imports into the Python it was built for
file(WRITE "${CMAKE_BINARY_DIR}/python_exe.txt" "${Python3_EXECUTABLE}")
message(STATUS "Carbon MMO: GLFW renderer ${CMMO_WITH_GLFW}")
