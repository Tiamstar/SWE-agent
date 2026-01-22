#!/usr/bin/env sh
set -e

cmake -S . -B build \
  -DCMAKE_CXX_STANDARD=14 \
  -Dprotobuf_BUILD_TESTS=OFF \
  -Dprotobuf_BUILD_EXAMPLES=OFF \
  -Dprotobuf_ABSL_PROVIDER=module   # 用子模块模式，不依赖系统 absl

cmake --build build
