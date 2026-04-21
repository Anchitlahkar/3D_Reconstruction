#include "raylib.h"
#include "raymath.h"

#include "alignment.h"
#include "ply_loader.h"

#include <algorithm>
#include <cstddef>
#include <cstdio>
#include <iostream>
#include <random>
#include <string>
#include <vector>

namespace {

constexpr std::size_t kMaxRenderedPointsDense = 500000;
constexpr std::size_t kMaxRenderedPointsLight = 150000;
constexpr float kMouseSensitivity = 0.003f;
constexpr float kBaseSpeed = 3.0f;

struct ViewerState {
    std::vector<Point> sourcePoints;
    std::vector<Point> alignedPoints;
    std::vector<Point> renderPoints;
    AlignmentResult alignment;
    bool denseMode = true;
    bool showGrid = true;
    float pointSize = 1.0f;
    bool isFlipped = false;
};

struct CameraState {
    Vector3 position = {0.0f, 1.0f, 3.0f};
    float yaw = 0.0f;
    float pitch = 0.0f;
    bool isRotating = false;
};

bool FileExistsSimple(const std::string& path) {
    FILE* file = nullptr;
#if defined(_MSC_VER)
    fopen_s(&file, path.c_str(), "rb");
#else
    file = fopen(path.c_str(), "rb");
#endif
    if (file == nullptr) {
        return false;
    }
    fclose(file);
    return true;
}

Vector3 ForwardFromYawPitch(float yaw, float pitch) {
    return Vector3Normalize({
        std::cos(pitch) * std::sin(yaw),
        std::sin(pitch),
        std::cos(pitch) * std::cos(yaw),
    });
}

Vector3 RightFromYaw(float yaw) {
    return Vector3Normalize({
        std::sin(yaw - PI / 2.0f),
        0.0f,
        std::cos(yaw - PI / 2.0f),
    });
}

void ResetCameraState(CameraState& state, Camera3D& camera) {
    state.position = {0.0f, 2.0f, 5.0f};
    state.yaw = PI;
    state.pitch = -0.3f;
    state.isRotating = false;
    camera.position = state.position;
    const Vector3 forward = ForwardFromYawPitch(state.yaw, state.pitch);
    camera.target = Vector3Add(camera.position, forward);
    camera.up = {0.0f, 1.0f, 0.0f};
    camera.fovy = 45.0f;
    camera.projection = CAMERA_PERSPECTIVE;
}

void UpdateCameraFPS(CameraState& state, Camera3D& camera) {
    const float dt = GetFrameTime();
    const float speed = IsKeyDown(KEY_LEFT_SHIFT) || IsKeyDown(KEY_RIGHT_SHIFT) ? kBaseSpeed * 2.0f : kBaseSpeed;

    if (IsMouseButtonPressed(MOUSE_BUTTON_RIGHT)) {
        state.isRotating = true;
        DisableCursor();
    }
    if (IsMouseButtonReleased(MOUSE_BUTTON_RIGHT)) {
        state.isRotating = false;
        EnableCursor();
    }

    if (state.isRotating) {
        const Vector2 delta = GetMouseDelta();
        state.yaw += delta.x * kMouseSensitivity;
        state.pitch += delta.y * kMouseSensitivity;
        state.pitch = Clamp(state.pitch, -1.5f, 1.5f);
    }

    const Vector3 forward = ForwardFromYawPitch(state.yaw, state.pitch);
    const Vector3 right = RightFromYaw(state.yaw);
    Vector3 movement = {0.0f, 0.0f, 0.0f};

    if (IsKeyDown(KEY_W)) movement = Vector3Add(movement, forward);
    if (IsKeyDown(KEY_S)) movement = Vector3Subtract(movement, forward);
    if (IsKeyDown(KEY_A)) movement = Vector3Subtract(movement, right);
    if (IsKeyDown(KEY_D)) movement = Vector3Add(movement, right);
    if (IsKeyDown(KEY_Q)) movement.y += 1.0f;
    if (IsKeyDown(KEY_E)) movement.y -= 1.0f;

    if (Vector3LengthSqr(movement) > 0.0f) {
        movement = Vector3Scale(Vector3Normalize(movement), speed * dt);
        state.position = Vector3Add(state.position, movement);
    }

    const float wheel = GetMouseWheelMove();
    if (wheel != 0.0f) {
        state.position = Vector3Add(state.position, Vector3Scale(forward, wheel * 0.5f));
    }

    camera.position = state.position;
    camera.target = Vector3Add(state.position, forward);
    camera.up = {0.0f, 1.0f, 0.0f};
}

std::vector<Point> SamplePoints(const std::vector<Point>& source, std::size_t limit) {
    if (source.size() <= limit) {
        return source;
    }

    std::vector<Point> sampled = source;
    std::mt19937 rng(1337);
    std::shuffle(sampled.begin(), sampled.end(), rng);
    sampled.resize(limit);
    return sampled;
}

void RefreshRenderPoints(ViewerState& state) {
    const std::size_t limit = state.denseMode ? kMaxRenderedPointsDense : kMaxRenderedPointsLight;
    state.renderPoints = SamplePoints(state.alignedPoints, limit);
    std::cout << "[viewer] render points: " << state.renderPoints.size() << " / " << state.alignedPoints.size() << '\n';
}

void RebuildAlignedCloud(ViewerState& state) {
    state.alignedPoints = state.sourcePoints;
    state.alignment = AlignPointCloudPCA(state.alignedPoints);
    state.isFlipped = false;
    RefreshRenderPoints(state);
}

void FlipY(ViewerState& state) {
    state.isFlipped = !state.isFlipped;
    for (auto& p : state.alignedPoints) p.y = -p.y;
    for (auto& p : state.renderPoints) p.y = -p.y;
}

void DrawPointCloud(const std::vector<Point>& points) {
    for (const Point& point : points) {
        DrawPoint3D({point.x, point.y, point.z}, {point.r, point.g, point.b, 255});
    }
}

}  // namespace

int main(int argc, char** argv) {
    const std::string defaultPath = "C:/dev/3D_Reconstruction/data/dense/0/fused.ply";
    const std::string plyPath = argc > 1 ? argv[1] : defaultPath;

    if (!FileExistsSimple(plyPath)) {
        std::cerr << "PLY file not found: " << plyPath << '\n';
        return 1;
    }

    ViewerState viewerState;
    try {
        viewerState.sourcePoints = LoadPLY(plyPath);
    } catch (const std::exception& error) {
        std::cerr << "Failed to load PLY: " << error.what() << '\n';
        return 1;
    }

    std::cout << "Loaded " << viewerState.sourcePoints.size() << " points from " << plyPath << '\n';
    if (viewerState.sourcePoints.empty()) {
        std::cerr << "Warning: point cloud is empty.\n";
        return 1;
    }

    RebuildAlignedCloud(viewerState);

    InitWindow(1280, 720, "3D Viewer");
    SetTargetFPS(60);

    Camera3D camera = {};
    CameraState cameraState;
    ResetCameraState(cameraState, camera);

    while (!WindowShouldClose()) {
        UpdateCameraFPS(cameraState, camera);

        if (IsKeyPressed(KEY_R)) {
            ResetCameraState(cameraState, camera);
            EnableCursor();
            std::cout << "[viewer] camera reset\n";
        }
        if (IsKeyPressed(KEY_V)) {
            viewerState.denseMode = !viewerState.denseMode;
            RefreshRenderPoints(viewerState);
            std::cout << "[viewer] density mode: " << (viewerState.denseMode ? "dense" : "light") << '\n';
        }
        if (IsKeyPressed(KEY_F)) {
            FlipY(viewerState);
            std::cout << "[viewer] flipped vertical orientation: " << (viewerState.isFlipped ? "flipped" : "original") << "\n";
        }
        if (IsKeyPressed(KEY_G)) {
            viewerState.showGrid = !viewerState.showGrid;
            std::cout << "[viewer] grid: " << (viewerState.showGrid ? "on" : "off") << "\n";
        }

        if (IsKeyPressed(KEY_U)) {
            RebuildAlignedCloud(viewerState);
            ResetCameraState(cameraState, camera);
            std::cout << "[viewer] reran PCA alignment\n";
        }

        BeginDrawing();
        ClearBackground(BLACK);

        BeginMode3D(camera);
        if (viewerState.showGrid) DrawGrid(20, 0.1f);
        DrawPointCloud(viewerState.renderPoints);
        EndMode3D();

        DrawFPS(10, 10);
        DrawText(TextFormat("Points: %i / %i", static_cast<int>(viewerState.renderPoints.size()), static_cast<int>(viewerState.alignedPoints.size())), 10, 34, 20, RAYWHITE);
        DrawText(TextFormat("PCA: %s", viewerState.alignment.success ? "aligned" : "fallback"), 10, 58, 20, RAYWHITE);
        DrawText(TextFormat("Density: %s", viewerState.denseMode ? "dense" : "light"), 10, 82, 20, RAYWHITE);
        DrawText(TextFormat("Orientation: %s", viewerState.isFlipped ? "FLIPPED" : "Normal"), 10, 106, 20, viewerState.isFlipped ? YELLOW : RAYWHITE);
        DrawText("RMB look | WASD move | Wheel zoom | Q/E up/down | Shift faster", 10, 134, 20, RAYWHITE);
        DrawText("F flip | V density | G grid | R reset | U rerun PCA", 10, 158, 20, RAYWHITE);

        EndDrawing();
    }


    if (cameraState.isRotating) {
        EnableCursor();
    }
    CloseWindow();
    return 0;
}

