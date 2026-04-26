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

struct PcaAnalysis {
    bool success = false;
    bool safeToAlign = false;
    Vector3 centroid = {0.0f, 0.0f, 0.0f};
    Vector3 principalAxis = {0.0f, 0.0f, 1.0f};
    std::array<float, 3> eigenvalues = {{0.0f, 0.0f, 0.0f}};
    const char* classification = "unknown";
};

float SignOrOne(float value) {
    return value < 0.0f ? -1.0f : 1.0f;
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

void SortEigenpairsDescending(SymmetricEigenDecomposition& decomposition) {
    std::array<int, 3> order = {{0, 1, 2}};
    std::sort(order.begin(), order.end(), [&](int left, int right) {
        return decomposition.eigenvalues[static_cast<std::size_t>(left)] > decomposition.eigenvalues[static_cast<std::size_t>(right)];
    });

    std::array<float, 3> sortedValues = {{0.0f, 0.0f, 0.0f}};
    std::array<std::array<float, 3>, 3> sortedVectors = {{
        {{0.0f, 0.0f, 0.0f}},
        {{0.0f, 0.0f, 0.0f}},
        {{0.0f, 0.0f, 0.0f}},
    }};

    for (int newColumn = 0; newColumn < 3; ++newColumn) {
        const int oldColumn = order[static_cast<std::size_t>(newColumn)];
        sortedValues[static_cast<std::size_t>(newColumn)] = decomposition.eigenvalues[static_cast<std::size_t>(oldColumn)];
        for (int row = 0; row < 3; ++row) {
            sortedVectors[static_cast<std::size_t>(row)][static_cast<std::size_t>(newColumn)] =
                decomposition.eigenvectors[static_cast<std::size_t>(row)][static_cast<std::size_t>(oldColumn)];
        }
    }

    decomposition.eigenvalues = sortedValues;
    decomposition.eigenvectors = sortedVectors;
}

Vector3 GetEigenvectorColumn(const std::array<std::array<float, 3>, 3>& matrix, int column) {
    return Vector3Normalize({matrix[0][column], matrix[1][column], matrix[2][column]});
}

const char* ClassifyCloudShape(float lambda1, float lambda2, float lambda3) {
    if (lambda1 <= std::numeric_limits<float>::epsilon()) {
        return "degenerate";
    }

    const float ratio21 = lambda2 / lambda1;
    const float ratio32 = lambda2 <= std::numeric_limits<float>::epsilon() ? 0.0f : lambda3 / lambda2;

    if (ratio21 < 0.2f && ratio32 < 0.2f) {
        return "linear";
    }
    if (ratio21 >= 0.6f && ratio32 < 0.2f) {
        return "planar";
    }
    if (ratio21 >= 0.6f && ratio32 >= 0.6f) {
        return "volumetric";
    }
    return "mixed";
}

PcaAnalysis AnalyzePointCloud(const std::vector<Point>& points) {
    PcaAnalysis analysis = {};
    if (points.size() < 3) {
        std::cout << "[alignment] not enough points for PCA\n";
        return analysis;
    }

    for (const Point& point : points) {
        analysis.centroid.x += point.x;
        analysis.centroid.y += point.y;
        analysis.centroid.z += point.z;
    }

    const float invCount = 1.0f / static_cast<float>(points.size());
    analysis.centroid.x *= invCount;
    analysis.centroid.y *= invCount;
    analysis.centroid.z *= invCount;

    std::array<std::array<float, 3>, 3> covariance = {{
        {{0.0f, 0.0f, 0.0f}},
        {{0.0f, 0.0f, 0.0f}},
        {{0.0f, 0.0f, 0.0f}},
    }};

    for (const Point& point : points) {
        const float x = point.x - analysis.centroid.x;
        const float y = point.y - analysis.centroid.y;
        const float z = point.z - analysis.centroid.z;
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

    SymmetricEigenDecomposition decomposition = JacobiEigenDecomposition(covariance);
    if (!decomposition.success) {
        std::cout << "[alignment] PCA decomposition did not converge, skipping alignment\n";
        return analysis;
    }

    SortEigenpairsDescending(decomposition);
    analysis.success = true;
    analysis.eigenvalues = decomposition.eigenvalues;
    analysis.principalAxis = GetEigenvectorColumn(decomposition.eigenvectors, 0);
    analysis.classification = ClassifyCloudShape(
        analysis.eigenvalues[0],
        analysis.eigenvalues[1],
        analysis.eigenvalues[2]
    );

    const float lambda1 = analysis.eigenvalues[0];
    const float lambda2 = analysis.eigenvalues[1];
    const float lambda3 = analysis.eigenvalues[2];
    const float ratio21 = lambda1 <= std::numeric_limits<float>::epsilon() ? 0.0f : lambda2 / lambda1;
    const float ratio32 = lambda2 <= std::numeric_limits<float>::epsilon() ? 0.0f : lambda3 / lambda2;

    analysis.safeToAlign = ratio21 < 0.5f && ratio32 < 0.5f;

    std::cout
        << "[alignment] eigenvalues=(" << lambda1 << ", " << lambda2 << ", " << lambda3 << ") "
        << "classification=" << analysis.classification << " "
        << "alignment=" << (analysis.safeToAlign ? "eligible" : "skipped") << '\n';

    return analysis;
}

void CenterPoints(std::vector<Point>& points, const Vector3& centroid) {
    for (Point& point : points) {
        point.x -= centroid.x;
        point.y -= centroid.y;
        point.z -= centroid.z;
    }
}

}  // namespace

AlignmentResult AlignPointCloudPCA(std::vector<Point>& points, bool enableAlignment) {
    AlignmentResult result;
    if (points.empty()) {
        std::cout << "[alignment] no points to align\n";
        return result;
    }

    const PcaAnalysis analysis = AnalyzePointCloud(points);
    result.success = analysis.success;
    result.centroid = analysis.centroid;
    result.principalEigenvector = analysis.principalAxis;
    result.eigenvalues = analysis.eigenvalues;
    result.classification = analysis.classification;

    CenterPoints(points, analysis.centroid);

    if (!enableAlignment) {
        std::cout << "[alignment] skipped rotation: manual alignment disabled\n";
        return result;
    }

    if (!analysis.success) {
        std::cout << "[alignment] skipped rotation: PCA unavailable\n";
        return result;
    }

    if (!analysis.safeToAlign) {
        std::cout << "[alignment] skipped rotation: shape not safe to align\n";
        return result;
    }

    const Vector3 sourceAxis = Vector3Normalize(analysis.principalAxis);
    const Vector3 targetAxis = {0.0f, 0.0f, 1.0f};
    Vector3 axis = Vector3CrossProduct(sourceAxis, targetAxis);
    const float axisLength = Vector3Length(axis);
    if (axisLength < 1e-6f) {
        std::cout << "[alignment] skipped rotation: source axis already aligned\n";
        return result;
    }

    axis = Vector3Scale(axis, 1.0f / axisLength);
    const float alignmentDot = std::clamp(Vector3DotProduct(sourceAxis, targetAxis), -1.0f, 1.0f);
    const float angle = std::acos(alignmentDot);
    ApplyRotationToPoints(points, axis, angle);
    result.alignmentApplied = true;
    std::cout << "[alignment] applied safe PCA rotation angle=" << angle << " radians\n";
    return result;
}
