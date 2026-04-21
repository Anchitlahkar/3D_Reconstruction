#pragma once

#include "ply_loader.h"

#include "raylib.h"

#include <vector>

struct AlignmentResult {
    bool success = false;
    Vector3 centroid = {0.0f, 0.0f, 0.0f};
    Vector3 smallestEigenvector = {0.0f, 1.0f, 0.0f};
    float scale = 1.0f;
};

AlignmentResult AlignPointCloudPCA(std::vector<Point>& points);
