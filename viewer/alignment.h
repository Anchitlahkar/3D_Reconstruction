#pragma once

#include "ply_loader.h"

#include "raylib.h"

#include <array>
#include <vector>

struct AlignmentResult {
    bool success = false;
    bool alignmentApplied = false;
    Vector3 centroid = {0.0f, 0.0f, 0.0f};
    Vector3 principalEigenvector = {0.0f, 0.0f, 1.0f};
    std::array<float, 3> eigenvalues = {{0.0f, 0.0f, 0.0f}};
    const char* classification = "unknown";
};

AlignmentResult AlignPointCloudPCA(std::vector<Point>& points, bool enableAlignment);
