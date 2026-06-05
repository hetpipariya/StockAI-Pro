"""
setup.py for StockAI Pro C++ Engine

Builds pybind11 extension module for ultra-fast feature engineering.

Build commands:
    python setup.py build_ext --inplace  (development build)
    pip install .                         (production install)
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path
from setuptools import setup, Extension
from setuptools.command.build_ext import build_ext

# CMAKE BUILD SYSTEM

class CMakeExtension(Extension):
    def __init__(self, name, sourcedir=''):
        Extension.__init__(self, name, sources=[])
        self.sourcedir = os.path.abspath(sourcedir)

class CMakeBuild(build_ext):
    def _cmake_cmd(self):
        if shutil.which('cmake'):
            return ['cmake']
        return [sys.executable, '-m', 'cmake']

    def run(self):
        for ext in self.extensions:
            self.build_cmake(ext)
    
    def build_cmake(self, ext):
        cmake_build_dir = Path(self.build_temp)
        cmake_build_dir.mkdir(parents=True, exist_ok=True)

        pybind11_cmake_dir = subprocess.check_output(
            [sys.executable, '-m', 'pybind11', '--cmakedir'],
            text=True,
        ).strip()
        
        # Configure CMake
        config_cmd = self._cmake_cmd() + [
            '-DCMAKE_BUILD_TYPE=Release',
            '-DCMAKE_LIBRARY_OUTPUT_DIRECTORY=' + str(self.build_lib),
            '-DPython3_EXECUTABLE=' + sys.executable,
            '-Dpybind11_DIR=' + pybind11_cmake_dir,
        ]

        # Platform-specific generator selection
        cmake_generator = os.environ.get('CMAKE_GENERATOR')
        if cmake_generator:
            config_cmd.extend(['-G', cmake_generator])
        elif sys.platform == 'win32' and shutil.which('ninja'):
            config_cmd.extend(['-G', 'Ninja'])
        elif sys.platform != 'win32':
            config_cmd.extend(['-G', 'Unix Makefiles'])
        
        config_cmd.append(ext.sourcedir)
        
        subprocess.check_call(config_cmd, cwd=str(cmake_build_dir))
        
        # Build
        build_cmd = self._cmake_cmd() + ['--build', '.', '--config', 'Release']
        subprocess.check_call(build_cmd, cwd=str(cmake_build_dir))

# SETUP

setup(
    name='stockai-cpp-engine',
    version='1.0.0',
    author='StockAI Pro',
    description='Ultra-high-performance C++ feature engineering engine for AI trading',
    long_description=Path('README.md').read_text(encoding='utf-8') if Path('README.md').exists() else '',
    long_description_content_type='text/markdown',
    ext_modules=[CMakeExtension('stockai_cpp_engine', '.')],
    cmdclass={'build_ext': CMakeBuild},
    zip_safe=False,
    install_requires=[
        'pybind11>=2.6.0',
        'numpy>=1.19.0',
    ],
    python_requires='>=3.7',
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
    ],
)


