cmake_minimum_required(VERSION 3.15)
project(stockai_cpp_engine LANGUAGES CXX)

# ────────────────────────────────────────────────────────────────────────────
# COMPILER SETTINGS
# ────────────────────────────────────────────────────────────────────────────

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
if(MSVC)
    set(CMAKE_CXX_FLAGS_RELEASE "/O2 /DNDEBUG")
    set(CMAKE_CXX_FLAGS_DEBUG "/Od /Zi")
else()
    set(CMAKE_CXX_FLAGS_RELEASE "-O3 -march=native -DNDEBUG")
    set(CMAKE_CXX_FLAGS_DEBUG "-O0 -g")
endif()

# Architecture-specific optimizations
if(MSVC)
    set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} /O2 /arch:AVX2")
else()
    set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -O3 -march=native")
endif()

# ────────────────────────────────────────────────────────────────────────────
# DEPENDENCIES
# ────────────────────────────────────────────────────────────────────────────

# Find Python
find_package(Python3 COMPONENTS Interpreter Development REQUIRED)
set(Python3_NumPy_INCLUDE_DIRS "C:/Users/PIPARIYA/AppData/Roaming/Python/Python310/site-packages/numpy/_core/include")

# pybind11
find_package(pybind11 CONFIG REQUIRED)

# ────────────────────────────────────────────────────────────────────────────
# SOURCE FILES
# ────────────────────────────────────────────────────────────────────────────

set(SOURCES
    bindings/module.cpp
)

set(HEADERS
    core/types.hpp
    core/constants.hpp
    core/math_utils.hpp
    indicators/ema.hpp
    indicators/momentum.hpp
    indicators/all_indicators.hpp
    feature_engine/feature_builder.hpp
)

# ────────────────────────────────────────────────────────────────────────────
# BUILD EXTENSION MODULE
# ────────────────────────────────────────────────────────────────────────────

pybind11_add_module(stockai_cpp_engine ${SOURCES})

# Link with NumPy
target_include_directories(stockai_cpp_engine PRIVATE ${Python3_NumPy_INCLUDE_DIRS})

# Copy the built extension into the backend package with a stable runtime name.
set(CPP_ENGINE_PACKAGE_DIR "${CMAKE_CURRENT_SOURCE_DIR}")
add_custom_command(
    TARGET stockai_cpp_engine
    POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
            $<TARGET_FILE:stockai_cpp_engine>
            "${CPP_ENGINE_PACKAGE_DIR}/stockai_cpp_engine.pyd"
    COMMENT "Copying stockai_cpp_engine into backend/app/cpp_engine"
    VERBATIM
)

# Performance flags
if(MSVC)
    target_compile_options(stockai_cpp_engine PRIVATE /O2)
else()
    target_compile_options(stockai_cpp_engine PRIVATE -O3 -march=native -ffast-math)
endif()

# ────────────────────────────────────────────────────────────────────────────
# UNIT TESTS (Optional)
# ────────────────────────────────────────────────────────────────────────────

option(BUILD_TESTS "Build unit tests" OFF)

if(BUILD_TESTS)
    enable_testing()
    
    # Test executable (without pybind11, just C++)
    add_executable(test_indicators tests/test_indicators.cpp)
    target_include_directories(test_indicators PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})
    if(MSVC)
        target_compile_options(test_indicators PRIVATE /O2)
    else()
        target_compile_options(test_indicators PRIVATE -O3)
    endif()
    
    add_test(NAME IndicatorTests COMMAND test_indicators)
endif()

# ────────────────────────────────────────────────────────────────────────────
# INSTALL SETTINGS
# ────────────────────────────────────────────────────────────────────────────

install(TARGETS stockai_cpp_engine DESTINATION .)
