#include "alignment.h"

#include "raymath.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <iostream>
#include <limits>

namespace {

struct SymmetricEigenDecomposition {
    std::array<std::array<float, 3>, 3> eigenvectors = {{
        {{1.0f, 0.0f, 0.0f}},
        {{0.0f, 1.0f, 0.0f}},
        {{0.0f, 0.0f, 1.0f}},
    }};
    std::array<float, 3> eigenvalues = {{0.0f, 0.0f, 0.0f}};
    bool success = false;
};

float SignOrOne(float value) {
    return value < 0.0f ? -1.0f : 1.0f;
}

Vector3 MatrixVectorMultiply(const std::array<std::array<float, 3>, 3>& matrix, const Vector3& vector) {
    return {
        matrix[0][0] * vector.x + matrix[0][1] * vector.y + matrix[0][2] * vector.z,
        matrix[1][0] * vector.x + matrix[1][1] * vector.y + matrix[1][2] * vector.z,
        matrix[2][0] * vector.x + matrix[2][1] * vector.y + matrix[2][2] * vector.z,
    };
}

Vector3 RotateVectorByAxisAngle(const Vector3& vector, const Vector3& axis, float angle) {
    const float cosine = std::cos(angle);
    const float sine = std::sin(angle);
    return Vector3Add(
        Vector3Add(
            Vector3Scale(vector, cosine),
            Vector3Scale(Vector3CrossProduct(axis, vector), sine)
        ),
        Vector3Scale(axis, Vector3DotProduct(axis, vector) * (1.0f - cosine))
    );
}

void ApplyRotationToPoints(std::vector<Point>& points, const Vector3& axis, float angle) {
    for (Point& point : points) {
        const Vector3 rotated = RotateVectorByAxisAngle({point.x, point.y, point.z}, axis, angle);
        point.x = rotated.x;
        point.y = rotated.y;
        point.z = rotated.z;
    }
}

void FlipYIfNeeded(std::vector<Point>& points) {
    std::size_t negativeY = 0;
    for (const Point& point : points) {
        if (point.y < 0.0f) {
            ++negativeY;
        }
    }

    if (negativeY > points.size() / 2) {
        for (Point& point : points) {
            point.y = -point.y;
        }
        std::cout << "[alignment] flipped Y axis to keep most points above ground\n";
    }
}

void NormalizeBoundingBox(std::vector<Point>& points, float& outScale) {
    outScale = 1.0f;
    if (points.empty()) {
        return;
    }

    Vector3 minPoint = {std::numeric_limits<float>::max(), std::numeric_limits<float>::max(), std::numeric_limits<float>::max()};
    Vector3 maxPoint = {-std::numeric_limits<float>::max(), -std::numeric_limits<float>::max(), -std::numeric_limits<float>::max()};

    for (const Point& point : points) {
        minPoint.x = std::min(minPoint.x, point.x);
        minPoint.y = std::min(minPoint.y, point.y);
        minPoint.z = std::min(minPoint.z, point.z);
        maxPoint.x = std::max(maxPoint.x, point.x);
        maxPoint.y = std::max(maxPoint.y, point.y);
        maxPoint.z = std::max(maxPoint.z, point.z);
    }

    const Vector3 center = {
        (minPoint.x + maxPoint.x) * 0.5f,
        (minPoint.y + maxPoint.y) * 0.5f,
        (minPoint.z + maxPoint.z) * 0.5f,
    };

    const float extentX = maxPoint.x - minPoint.x;
    const float extentY = maxPoint.y - minPoint.y;
    const float extentZ = maxPoint.z - minPoint.z;
    const float maxExtent = std::max(extentX, std::max(extentY, extentZ));

    for (Point& point : points) {
        point.x -= center.x;
        point.y -= center.y;
        point.z -= center.z;
    }

    if (maxExtent <= std::numeric_limits<float>::epsilon()) {
        std::cout << "[alignment] skipped normalization scaling because bounding box extent is zero\n";
        return;
    }

    outScale = 2.0f / maxExtent;
    for (Point& point : points) {
        point.x *= outScale;
        point.y *= outScale;
        point.z *= outScale;
    }
}

SymmetricEigenDecomposition JacobiEigenDecomposition(std::array<std::array<float, 3>, 3> matrix) {
    SymmetricEigenDecomposition result;

    constexpr int kMaxIterations = 24;
    constexpr float kTolerance = 1e-6f;

    for (int iteration = 0; iteration < kMaxIterations; ++iteration) {
        int p = 0;
        int q = 1;
        float maxOffDiagonal = std::fabs(matrix[0][1]);

        if (std::fabs(matrix[0][2]) > maxOffDiagonal) {
            p = 0;
            q = 2;
            maxOffDiagonal = std::fabs(matrix[0][2]);
        }
        if (std::fabs(matrix[1][2]) > maxOffDiagonal) {
            p = 1;
            q = 2;
            maxOffDiagonal = std::fabs(matrix[1][2]);
        }

        if (maxOffDiagonal < kTolerance) {
            result.success = true;
            break;
        }

        const float app = matrix[p][p];
        const float aqq = matrix[q][q];
        const float apq = matrix[p][q];
        if (std::fabs(apq) < kTolerance) {
            continue;
        }

        const float tau = (aqq - app) / (2.0f * apq);
        const float tangent = SignOrOne(tau) / (std::fabs(tau) + std::sqrt(1.0f + tau * tau));
        const float cosine = 1.0f / std::sqrt(1.0f + tangent * tangent);
        const float sine = tangent * cosine;

        matrix[p][p] = app - tangent * apq;
        matrix[q][q] = aqq + tangent * apq;
        matrix[p][q] = 0.0f;
        matrix[q][p] = 0.0f;

        for (int r = 0; r < 3; ++r) {
            if (r == p || r == q) {
                continue;
            }
            const float arp = matrix[r][p];
            const float arq = matrix[r][q];
            matrix[r][p] = cosine * arp - sine * arq;
            matrix[p][r] = matrix[r][p];
            matrix[r][q] = cosine * arq + sine * arp;
            matrix[q][r] = matrix[r][q];
        }

        for (int r = 0; r < 3; ++r) {
            const float vrp = result.eigenvectors[r][p];
            const float vrq = result.eigenvectors[r][q];
            result.eigenvectors[r][p] = cosine * vrp - sine * vrq;
            result.eigenvectors[r][q] = cosine * vrq + sine * vrp;
        }
    }

    result.eigenvalues = {{matrix[0][0], matrix[1][1], matrix[2][2]}};
    if (!result.success) {
        const float residual = std::fabs(matrix[0][1]) + std::fabs(matrix[0][2]) + std::fabs(matrix[1][2]);
        result.success = residual < 1e-4f;
    }

    return result;
}

Vector3 GetEigenvectorColumn(const std::array<std::array<float, 3>, 3>& matrix, int column) {
    return Vector3Normalize({matrix[0][column], matrix[1][column], matrix[2][column]});
}

bool ComputeSmallestEigenvector(const std::vector<Point>& points, Vector3& outCentroid, Vector3& outAxis) {
    if (points.size() < 3) {
        std::cout << "[alignment] not enough points for PCA\n";
        return false;
    }

    outCentroid = {0.0f, 0.0f, 0.0f};
    for (const Point& point : points) {
        outCentroid.x += point.x;
        outCentroid.y += point.y;
        outCentroid.z += point.z;
    }

    const float invCount = 1.0f / static_cast<float>(points.size());
    outCentroid.x *= invCount;
    outCentroid.y *= invCount;
    outCentroid.z *= invCount;

    std::array<std::array<float, 3>, 3> covariance = {{
        {{0.0f, 0.0f, 0.0f}},
        {{0.0f, 0.0f, 0.0f}},
        {{0.0f, 0.0f, 0.0f}},
    }};

    for (const Point& point : points) {
        const float x = point.x - outCentroid.x;
        const float y = point.y - outCentroid.y;
        const float z = point.z - outCentroid.z;
        covariance[0][0] += x * x;
        covariance[0][1] += x * y;
        covariance[0][2] += x * z;
        covariance[1][0] += y * x;
        covariance[1][1] += y * y;
        covariance[1][2] += y * z;
        covariance[2][0] += z * x;
        covariance[2][1] += z * y;
        covariance[2][2] += z * z;
    }

    const SymmetricEigenDecomposition decomposition = JacobiEigenDecomposition(covariance);
    if (!decomposition.success) {
        std::cout << "[alignment] PCA decomposition did not converge, using fallback orientation\n";
        return false;
    }

    int smallestIndex = 0;
    if (decomposition.eigenvalues[1] < decomposition.eigenvalues[smallestIndex]) {
        smallestIndex = 1;
    }
    if (decomposition.eigenvalues[2] < decomposition.eigenvalues[smallestIndex]) {
        smallestIndex = 2;
    }

    outAxis = GetEigenvectorColumn(decomposition.eigenvectors, smallestIndex);
    if (Vector3Length(outAxis) <= std::numeric_limits<float>::epsilon()) {
        std::cout << "[alignment] PCA returned near-zero axis, using fallback orientation\n";
        return false;
    }

    std::cout
        << "[alignment] centroid=(" << outCentroid.x << ", " << outCentroid.y << ", " << outCentroid.z << ") "
        << "smallest_eigenvector=(" << outAxis.x << ", " << outAxis.y << ", " << outAxis.z << ")\n";
    return true;
}

}  // namespace

AlignmentResult AlignPointCloudPCA(std::vector<Point>& points) {
    AlignmentResult result;
    if (points.empty()) {
        std::cout << "[alignment] no points to align\n";
        return result;
    }

    Vector3 centroid = {0.0f, 0.0f, 0.0f};
    Vector3 smallestEigenvector = {0.0f, 1.0f, 0.0f};

    const bool pcaReady = ComputeSmallestEigenvector(points, centroid, smallestEigenvector);

    for (Point& point : points) {
        point.x -= centroid.x;
        point.y -= centroid.y;
        point.z -= centroid.z;
    }

    if (pcaReady) {
        Vector3 axis = Vector3CrossProduct(smallestEigenvector, {0.0f, 1.0f, 0.0f});
        float axisLength = Vector3Length(axis);
        const float alignmentDot = std::clamp(Vector3DotProduct(Vector3Normalize(smallestEigenvector), {0.0f, 1.0f, 0.0f}), -1.0f, 1.0f);

        if (axisLength <= 1e-6f) {
            if (alignmentDot < 0.0f) {
                axis = {1.0f, 0.0f, 0.0f};
                axisLength = 1.0f;
                ApplyRotationToPoints(points, axis, PI);
                std::cout << "[alignment] rotated 180 degrees to invert vertical axis\n";
            } else {
                std::cout << "[alignment] point cloud already aligned with world Y axis\n";
            }
        } else {
            axis = Vector3Scale(axis, 1.0f / axisLength);
            const float angle = std::acos(alignmentDot);
            ApplyRotationToPoints(points, axis, angle);
            std::cout << "[alignment] applied PCA rotation angle=" << angle << " radians\n";
        }
    } else {
        std::cout << "[alignment] using centroid-only fallback\n";
    }

    FlipYIfNeeded(points);
    NormalizeBoundingBox(points, result.scale);

    result.success = pcaReady;
    result.centroid = centroid;
    result.smallestEigenvector = smallestEigenvector;
    return result;
}
