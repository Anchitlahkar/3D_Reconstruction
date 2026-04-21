#include "raylib.h"
#include "raymath.h"
#include "rlgl.h"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <iostream>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

struct Point {
    float x, y, z;
    unsigned char r, g, b;
};

struct PlyProperty {
    std::string type;
    std::string name;
};

struct PointCloudInfo {
    bool hasColor = false;
    Vector3 originalCenter = {0.0f, 0.0f, 0.0f};
    float normalizationScale = 1.0f;
};

static bool FileExists(const std::string& path) {
    std::ifstream file(path);
    return file.good();
}

static void TrimTrailingCarriageReturn(std::string& value) {
    if (!value.empty() && value.back() == '\r') {
        value.pop_back();
    }
}

static std::string ResolveDefaultPlyPath() {
    const char* candidates[] = {
        "data/dense/fused.ply",
        "../data/dense/fused.ply",
        "data/dense/0/fused.ply",
        "../data/dense/0/fused.ply",
        "data/dense/meshed-poisson.ply",
        "../data/dense/meshed-poisson.ply",
        "data/dense/0/meshed-poisson.ply",
        "../data/dense/0/meshed-poisson.ply"
    };

    for (const char* path : candidates) {
        if (FileExists(path)) return path;
    }

    return "data/dense/fused.ply";
}

static std::string ToLower(std::string value) {
    for (char& ch : value) {
        ch = static_cast<char>(std::tolower(static_cast<unsigned char>(ch)));
    }
    return value;
}

static int FindPropertyIndex(const std::vector<PlyProperty>& properties, const std::string& name) {
    for (int i = 0; i < static_cast<int>(properties.size()); ++i) {
        if (properties[i].name == name) return i;
    }
    return -1;
}

static unsigned char ClampColor(double value) {
    value = std::clamp(value, 0.0, 255.0);
    return static_cast<unsigned char>(value);
}

static int PropertySize(const std::string& type) {
    if (type == "char" || type == "uchar" || type == "int8" || type == "uint8") return 1;
    if (type == "short" || type == "ushort" || type == "int16" || type == "uint16") return 2;
    if (type == "int" || type == "uint" || type == "float" || type == "int32" || type == "uint32" || type == "float32") return 4;
    if (type == "double" || type == "float64") return 8;
    throw std::runtime_error("Unsupported PLY property type: " + type);
}

static double ReadNumericLittleEndian(std::ifstream& file, const std::string& type) {
    unsigned char bytes[8] = {};
    const int byteCount = PropertySize(type);
    file.read(reinterpret_cast<char*>(bytes), byteCount);

    if (type == "float" || type == "float32") {
        std::uint32_t raw = 0;
        for (int i = 0; i < 4; ++i) raw |= static_cast<std::uint32_t>(bytes[i]) << (8 * i);
        float value = 0.0f;
        std::memcpy(&value, &raw, sizeof(float));
        return value;
    }

    if (type == "double" || type == "float64") {
        std::uint64_t raw = 0;
        for (int i = 0; i < 8; ++i) raw |= static_cast<std::uint64_t>(bytes[i]) << (8 * i);
        double value = 0.0;
        std::memcpy(&value, &raw, sizeof(double));
        return value;
    }

    std::uint64_t raw = 0;
    for (int i = 0; i < byteCount; ++i) raw |= static_cast<std::uint64_t>(bytes[i]) << (8 * i);
    return static_cast<double>(raw);
}

static std::vector<Point> LoadPly(const std::string& path, PointCloudInfo& info) {
    std::ifstream file(path, std::ios::binary);
    if (!file) {
        throw std::runtime_error("Could not open PLY file: " + path);
    }

    std::string line;
    std::getline(file, line);
    TrimTrailingCarriageReturn(line);
    if (line != "ply") {
        throw std::runtime_error("Input is not a PLY file.");
    }

    int vertexCount = 0;
    bool readingVertexProperties = false;
    bool asciiFormat = false;
    bool binaryLittleEndian = false;
    std::vector<PlyProperty> properties;

    while (std::getline(file, line)) {
        TrimTrailingCarriageReturn(line);
        if (line == "end_header") break;

        std::istringstream header(line);
        std::string token;
        header >> token;

        if (token == "format") {
            std::string format;
            header >> format;
            asciiFormat = format == "ascii";
            binaryLittleEndian = format == "binary_little_endian";
        } else if (token == "element") {
            std::string elementName;
            header >> elementName;
            readingVertexProperties = elementName == "vertex";
            if (readingVertexProperties) header >> vertexCount;
        } else if (token == "property" && readingVertexProperties) {
            std::string type;
            std::string name;
            header >> type >> name;

            if (type == "list") {
                std::string countType;
                std::string itemType;
                header >> countType >> itemType >> name;
            }

            properties.push_back({ToLower(type), ToLower(name)});
        }
    }

    if (!asciiFormat && !binaryLittleEndian) {
        throw std::runtime_error("Only ASCII and binary_little_endian PLY files are supported.");
    }
    if (vertexCount <= 0) {
        throw std::runtime_error("PLY file does not contain vertices.");
    }

    const int xIndex = FindPropertyIndex(properties, "x");
    const int yIndex = FindPropertyIndex(properties, "y");
    const int zIndex = FindPropertyIndex(properties, "z");
    if (xIndex < 0 || yIndex < 0 || zIndex < 0) {
        throw std::runtime_error("PLY vertex data must contain x, y, and z properties.");
    }

    int rIndex = FindPropertyIndex(properties, "red");
    int gIndex = FindPropertyIndex(properties, "green");
    int bIndex = FindPropertyIndex(properties, "blue");
    if (rIndex < 0) rIndex = FindPropertyIndex(properties, "r");
    if (gIndex < 0) gIndex = FindPropertyIndex(properties, "g");
    if (bIndex < 0) bIndex = FindPropertyIndex(properties, "b");
    info.hasColor = rIndex >= 0 && gIndex >= 0 && bIndex >= 0;

    std::vector<Point> points;
    points.reserve(static_cast<size_t>(vertexCount));

    std::vector<double> values(properties.size(), 0.0);
    for (int i = 0; i < vertexCount; ++i) {
        if (asciiFormat) {
            if (!std::getline(file, line)) break;
            TrimTrailingCarriageReturn(line);
            if (line.empty()) {
                --i;
                continue;
            }

            std::istringstream row(line);
            for (double& value : values) {
                row >> value;
            }
        } else {
            for (int propertyIndex = 0; propertyIndex < static_cast<int>(properties.size()); ++propertyIndex) {
                values[propertyIndex] = ReadNumericLittleEndian(file, properties[propertyIndex].type);
            }
        }

        Point point = {};
        point.x = static_cast<float>(values[xIndex]);
        point.y = static_cast<float>(values[yIndex]);
        point.z = static_cast<float>(values[zIndex]);
        point.r = info.hasColor ? ClampColor(values[rIndex]) : 255;
        point.g = info.hasColor ? ClampColor(values[gIndex]) : 255;
        point.b = info.hasColor ? ClampColor(values[bIndex]) : 255;
        points.push_back(point);
    }

    if (points.empty()) {
        throw std::runtime_error("PLY vertex section was empty or unreadable.");
    }

    return points;
}

static void NormalizePointCloud(std::vector<Point>& points, PointCloudInfo& info) {
    Vector3 minPoint = {
        std::numeric_limits<float>::max(),
        std::numeric_limits<float>::max(),
        std::numeric_limits<float>::max()
    };
    Vector3 maxPoint = {
        -std::numeric_limits<float>::max(),
        -std::numeric_limits<float>::max(),
        -std::numeric_limits<float>::max()
    };

    for (const Point& point : points) {
        minPoint.x = std::min(minPoint.x, point.x);
        minPoint.y = std::min(minPoint.y, point.y);
        minPoint.z = std::min(minPoint.z, point.z);
        maxPoint.x = std::max(maxPoint.x, point.x);
        maxPoint.y = std::max(maxPoint.y, point.y);
        maxPoint.z = std::max(maxPoint.z, point.z);
    }

    info.originalCenter = {
        (minPoint.x + maxPoint.x) * 0.5f,
        (minPoint.y + maxPoint.y) * 0.5f,
        (minPoint.z + maxPoint.z) * 0.5f
    };

    const float sizeX = maxPoint.x - minPoint.x;
    const float sizeY = maxPoint.y - minPoint.y;
    const float sizeZ = maxPoint.z - minPoint.z;
    const float largestSize = std::max(sizeX, std::max(sizeY, sizeZ));
    info.normalizationScale = largestSize > 0.0f ? 8.0f / largestSize : 1.0f;

    for (Point& point : points) {
        point.x = (point.x - info.originalCenter.x) * info.normalizationScale;
        point.y = (point.y - info.originalCenter.y) * info.normalizationScale;
        point.z = (point.z - info.originalCenter.z) * info.normalizationScale;
    }
}

static Vector3 CameraForward(float yaw, float pitch) {
    return Vector3Normalize({
        std::cos(pitch) * std::sin(yaw),
        std::sin(pitch),
        std::cos(pitch) * std::cos(yaw)
    });
}

static Vector3 CameraRight(const Vector3& forward) {
    return Vector3Normalize(Vector3CrossProduct(forward, {0.0f, 1.0f, 0.0f}));
}

static void ResetCamera(Camera3D& camera, float& yaw, float& pitch) {
    camera.position = {0.0f, 1.5f, -12.0f};
    yaw = 0.0f;
    pitch = 0.0f;
    camera.up = {0.0f, 1.0f, 0.0f};
    camera.fovy = 45.0f;
    camera.projection = CAMERA_PERSPECTIVE;
    camera.target = Vector3Add(camera.position, CameraForward(yaw, pitch));
}

static void UpdateFreeCamera(Camera3D& camera, float& yaw, float& pitch) {
    const float dt = GetFrameTime();
    const float mouseSensitivity = 0.003f;
    const float baseSpeed = IsKeyDown(KEY_LEFT_SHIFT) || IsKeyDown(KEY_RIGHT_SHIFT) ? 14.0f : 5.0f;

    if (IsMouseButtonDown(MOUSE_BUTTON_RIGHT)) {
        const Vector2 mouseDelta = GetMouseDelta();
        yaw -= mouseDelta.x * mouseSensitivity;
        pitch -= mouseDelta.y * mouseSensitivity;
        pitch = std::clamp(pitch, -1.55f, 1.55f);
    }

    Vector3 forward = CameraForward(yaw, pitch);
    Vector3 right = CameraRight(forward);
    Vector3 move = {0.0f, 0.0f, 0.0f};

    if (IsKeyDown(KEY_W)) move = Vector3Add(move, forward);
    if (IsKeyDown(KEY_S)) move = Vector3Subtract(move, forward);
    if (IsKeyDown(KEY_D)) move = Vector3Add(move, right);
    if (IsKeyDown(KEY_A)) move = Vector3Subtract(move, right);
    if (IsKeyDown(KEY_E)) move.y += 1.0f;
    if (IsKeyDown(KEY_Q)) move.y -= 1.0f;

    const float wheel = GetMouseWheelMove();
    if (wheel != 0.0f) {
        move = Vector3Add(move, Vector3Scale(forward, wheel * 5.0f));
    }

    if (Vector3LengthSqr(move) > 0.0f) {
        camera.position = Vector3Add(camera.position, Vector3Scale(Vector3Normalize(move), baseSpeed * dt));
    }

    camera.target = Vector3Add(camera.position, forward);
}

static void DrawPointCloud(const std::vector<Point>& points, const Camera3D& camera, float pointSize) {
    const Vector3 forward = Vector3Normalize(Vector3Subtract(camera.target, camera.position));
    const Vector3 right = Vector3Normalize(Vector3CrossProduct(forward, camera.up));
    const Vector3 up = Vector3Normalize(Vector3CrossProduct(right, forward));
    const float halfSize = 0.006f * pointSize;
    const Vector3 rightOffset = Vector3Scale(right, halfSize);
    const Vector3 upOffset = Vector3Scale(up, halfSize);

    rlBegin(RL_QUADS);
    for (const Point& point : points) {
        const Vector3 center = {point.x, point.y, point.z};
        const Vector3 topLeft = Vector3Add(Vector3Subtract(center, rightOffset), upOffset);
        const Vector3 topRight = Vector3Add(Vector3Add(center, rightOffset), upOffset);
        const Vector3 bottomRight = Vector3Subtract(Vector3Add(center, rightOffset), upOffset);
        const Vector3 bottomLeft = Vector3Subtract(Vector3Subtract(center, rightOffset), upOffset);

        rlColor4ub(point.r, point.g, point.b, 255);
        rlVertex3f(topLeft.x, topLeft.y, topLeft.z);
        rlVertex3f(bottomLeft.x, bottomLeft.y, bottomLeft.z);
        rlVertex3f(bottomRight.x, bottomRight.y, bottomRight.z);
        rlVertex3f(topRight.x, topRight.y, topRight.z);
    }
    rlEnd();
}

static void DrawOverlay(int pointCount, bool hasColor, float pointSize, bool showGrid, const std::string& plyPath) {
    const int panelWidth = 460;
    const int panelHeight = 210;
    DrawRectangle(12, 12, panelWidth, panelHeight, {0, 0, 0, 150});
    DrawRectangleLines(12, 12, panelWidth, panelHeight, {255, 255, 255, 55});

    DrawText(TextFormat("FPS: %d", GetFPS()), 24, 24, 20, RAYWHITE);
    DrawText(TextFormat("Points: %d", pointCount), 24, 50, 20, RAYWHITE);
    DrawText(TextFormat("Color: %s", hasColor ? "PLY RGB" : "default white"), 24, 76, 20, RAYWHITE);
    DrawText(TextFormat("Point size: %.0f", pointSize), 24, 102, 20, RAYWHITE);
    DrawText(TextFormat("Grid: %s", showGrid ? "on" : "off"), 24, 128, 20, RAYWHITE);

    DrawText("RMB drag rotate | Wheel zoom | WASD move | Q/E up/down", 24, 158, 16, LIGHTGRAY);
    DrawText("Shift faster | 1/2/3 point size | G grid | R reset", 24, 180, 16, LIGHTGRAY);

    const std::string fileLine = "File: " + plyPath;
    DrawText(fileLine.c_str(), 12, GetScreenHeight() - 28, 16, LIGHTGRAY);
}

int main(int argc, char** argv) {
    const std::string plyPath = argc > 1 ? argv[1] : ResolveDefaultPlyPath();

    PointCloudInfo cloudInfo;
    std::vector<Point> points;
    try {
        points = LoadPly(plyPath, cloudInfo);
        NormalizePointCloud(points, cloudInfo);
    } catch (const std::exception& error) {
        std::cerr << "Viewer error: " << error.what() << '\n';
        std::cerr << "Usage: viewer.exe path\\to\\cloud.ply\n";
        return 1;
    }

    std::cout << "Loaded " << points.size() << " points from " << plyPath << '\n';
    std::cout << "Controls: RMB drag rotate, wheel zoom, WASD move, Q/E up/down, Shift fast.\n";

    SetConfigFlags(FLAG_MSAA_4X_HINT | FLAG_WINDOW_RESIZABLE);
    InitWindow(1280, 720, "Raylib PLY Point Cloud Viewer");
    SetTargetFPS(60);

    Camera3D camera = {};
    float yaw = 0.0f;
    float pitch = 0.0f;
    ResetCamera(camera, yaw, pitch);

    float pointSize = 1.0f;
    bool showGrid = true;

    while (!WindowShouldClose()) {
        if (IsKeyPressed(KEY_ONE)) pointSize = 1.0f;
        if (IsKeyPressed(KEY_TWO)) pointSize = 2.0f;
        if (IsKeyPressed(KEY_THREE)) pointSize = 3.0f;
        if (IsKeyPressed(KEY_G)) showGrid = !showGrid;
        if (IsKeyPressed(KEY_R)) ResetCamera(camera, yaw, pitch);

        UpdateFreeCamera(camera, yaw, pitch);

        BeginDrawing();
        ClearBackground({18, 19, 22, 255});

        BeginMode3D(camera);
        if (showGrid) {
            DrawGrid(24, 0.5f);
        }
        DrawPointCloud(points, camera, pointSize);
        EndMode3D();

        DrawOverlay(static_cast<int>(points.size()), cloudInfo.hasColor, pointSize, showGrid, plyPath);

        EndDrawing();
    }

    CloseWindow();
    return 0;
}
