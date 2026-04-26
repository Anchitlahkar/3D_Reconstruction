extern "C" {
    __declspec(dllexport) unsigned long NvOptimusEnablement = 0x00000001;
}
extern "C" {
    __declspec(dllexport) int AmdPowerXpressRequestHighPerformance = 1;
}

using GLubyte = unsigned char;
constexpr unsigned int GL_RENDERER = 0x1F01;
constexpr unsigned int GL_POINTS = 0x0000;
extern "C" const GLubyte* glGetString(unsigned int name);
extern "C" void glPointSize(float size);
extern "C" void glDrawArrays(unsigned int mode, int first, int count);

#include "raylib.h"
#include "raymath.h"
#include "rlgl.h"

#include "alignment.h"
#include "ply_loader.h"

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdio>
#include <iostream>
#include <limits>
#include <random>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

constexpr std::size_t kSampleThreshold = 1000000;
constexpr std::size_t kSampleLimit = 500000;
constexpr float kMouseSensitivity = 0.003f;
constexpr float kBaseSpeed = 3.0f;
constexpr float kNearPlane = 0.01f;
constexpr float kFarPlane = 1000.0f;

struct GPUPoint {
    float x;
    float y;
    float z;
    unsigned char r;
    unsigned char g;
    unsigned char b;
    unsigned char a;
};

struct PointCloudRenderer {
    unsigned int vaoId = 0;
    unsigned int vboId = 0;
    Shader shader = {};
    int mvpLocation = -1;
    int pointCount = 0;
};

struct ViewerState {
    std::vector<Point> sourcePoints;
    std::vector<Point> alignedPoints;
    std::vector<Point> renderPoints;
    AlignmentResult alignment;
    bool enableAlignment = false;
    bool normalize = false;
    bool showGrid = true;
    float pointSize = 2.0f;
};

struct CameraState {
    Vector3 position = {0.0f, 1.0f, 3.0f};
    float yaw = 0.0f;
    float pitch = 0.0f;
    bool isRotating = false;
};

void UploadPointCloud(PointCloudRenderer& renderer, const std::vector<Point>& points);

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
    float speedMultiplier = 1.0f;
    if (IsKeyDown(KEY_LEFT_SHIFT) || IsKeyDown(KEY_RIGHT_SHIFT)) {
        speedMultiplier = 5.0f;
    }
    if (IsKeyDown(KEY_LEFT_CONTROL) || IsKeyDown(KEY_RIGHT_CONTROL)) {
        speedMultiplier = 0.2f;
    }
    const float speed = kBaseSpeed * speedMultiplier;

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
    if (IsKeyDown(KEY_Q)) movement.y -= 1.0f;
    if (IsKeyDown(KEY_E)) movement.y += 1.0f;

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

bool IsRenderablePoint(const Point& point) {
    const auto validCoord = [](float value) {
        return std::isfinite(value) && std::fabs(value) <= 10000.0f;
    };
    return validCoord(point.x) && validCoord(point.y) && validCoord(point.z);
}

std::vector<Point> FilterAndSamplePoints(const std::vector<Point>& source) {
    std::vector<Point> filtered;
    filtered.reserve(source.size());

    std::size_t discarded = 0;
    for (const Point& point : source) {
        if (IsRenderablePoint(point)) {
            filtered.push_back(point);
        } else {
            ++discarded;
        }
    }

    if (discarded > 0) {
        std::cout << "[viewer] discarded invalid points: " << discarded << '\n';
    }

    if (filtered.size() > kSampleThreshold) {
        std::mt19937 rng(1337);
        std::shuffle(filtered.begin(), filtered.end(), rng);
        filtered.resize(kSampleLimit);
        std::cout << "[viewer] sampled point cloud to " << filtered.size() << " points for rendering\n";
    }

    return filtered;
}

void RefreshPointCloudGPU(ViewerState& state, PointCloudRenderer& renderer) {
    state.renderPoints = FilterAndSamplePoints(state.alignedPoints);
    UploadPointCloud(renderer, state.renderPoints);
    std::printf("Points: %d\n", renderer.pointCount);
}

void ApplyRobustNormalization(std::vector<Point>& points) {
    if (points.empty()) {
        return;
    }

    std::vector<float> xs;
    std::vector<float> ys;
    std::vector<float> zs;
    xs.reserve(points.size());
    ys.reserve(points.size());
    zs.reserve(points.size());

    for (const Point& point : points) {
        xs.push_back(point.x);
        ys.push_back(point.y);
        zs.push_back(point.z);
    }

    auto quantile = [](std::vector<float>& values, float fraction) {
        const std::size_t index = static_cast<std::size_t>(fraction * static_cast<float>(values.size() - 1));
        std::nth_element(values.begin(), values.begin() + static_cast<std::ptrdiff_t>(index), values.end());
        return values[index];
    };

    constexpr float kLowQuantile = 0.005f;
    constexpr float kHighQuantile = 0.995f;
    const float minX = quantile(xs, kLowQuantile);
    const float maxX = quantile(xs, kHighQuantile);
    const float minY = quantile(ys, kLowQuantile);
    const float maxY = quantile(ys, kHighQuantile);
    const float minZ = quantile(zs, kLowQuantile);
    const float maxZ = quantile(zs, kHighQuantile);

    const float extentX = maxX - minX;
    const float extentY = maxY - minY;
    const float extentZ = maxZ - minZ;
    const float maxExtent = std::max(extentX, std::max(extentY, extentZ));

    if (maxExtent <= std::numeric_limits<float>::epsilon()) {
        std::cout << "[viewer] skipped normalization: trimmed bounds collapsed\n";
        return;
    }

    const float scale = 2.0f / maxExtent;
    for (Point& point : points) {
        point.x *= scale;
        point.y *= scale;
        point.z *= scale;
    }

    std::cout << "[viewer] applied robust normalization scale=" << scale << '\n';
}

const char* GetPointCloudVertexShader() {
    return R"(
        #version 330
        layout(location = 0) in vec3 vertexPosition;
        layout(location = 1) in vec4 vertexColor;
        uniform mat4 mvp;
        out vec4 fragColor;
        void main() {
            fragColor = vertexColor;
            gl_Position = mvp*vec4(vertexPosition, 1.0);
        }
    )";
}

const char* GetPointCloudFragmentShader() {
    return R"(
        #version 330
        in vec4 fragColor;
        out vec4 finalColor;
        void main() {
            finalColor = fragColor;
        }
    )";
}

void EnsureRendererShader(PointCloudRenderer& renderer) {
    if (renderer.shader.id != 0) {
        return;
    }

    renderer.shader = LoadShaderFromMemory(GetPointCloudVertexShader(), GetPointCloudFragmentShader());
    if (renderer.shader.id == 0) {
        throw std::runtime_error("Failed to load point cloud shader.");
    }

    renderer.mvpLocation = GetShaderLocation(renderer.shader, "mvp");
    if (renderer.mvpLocation < 0) {
        throw std::runtime_error("Point cloud shader is missing mvp uniform.");
    }
}

std::vector<GPUPoint> BuildGPUPoints(const std::vector<Point>& points) {
    std::vector<GPUPoint> gpuPoints;
    gpuPoints.reserve(points.size());

    for (const Point& point : points) {
        gpuPoints.push_back({point.x, point.y, point.z, point.r, point.g, point.b, 255});
    }

    return gpuPoints;
}

void UploadPointCloud(PointCloudRenderer& renderer, const std::vector<Point>& points) {
    renderer.pointCount = 0;

    if (renderer.vboId != 0) {
        rlUnloadVertexBuffer(renderer.vboId);
        renderer.vboId = 0;
    }
    if (renderer.vaoId != 0) {
        rlUnloadVertexArray(renderer.vaoId);
        renderer.vaoId = 0;
    }

    const std::vector<GPUPoint> gpuPoints = BuildGPUPoints(points);
    if (gpuPoints.empty()) {
        return;
    }

    renderer.vaoId = rlLoadVertexArray();
    renderer.vboId = rlLoadVertexBuffer(gpuPoints.data(), static_cast<int>(gpuPoints.size() * sizeof(GPUPoint)), false);
    renderer.pointCount = static_cast<int>(gpuPoints.size());

    if (renderer.vaoId != 0) {
        rlEnableVertexArray(renderer.vaoId);
    }

    rlEnableVertexBuffer(renderer.vboId);
    rlSetVertexAttribute(0, 3, RL_FLOAT, false, sizeof(GPUPoint), 0);
    rlEnableVertexAttribute(0);
    rlSetVertexAttribute(1, 4, RL_UNSIGNED_BYTE, true, sizeof(GPUPoint), 3 * static_cast<int>(sizeof(float)));
    rlEnableVertexAttribute(1);

    if (renderer.vaoId != 0) {
        rlDisableVertexArray();
    }
    rlDisableVertexBuffer();

    std::cout << "[viewer] uploaded " << renderer.pointCount << " GPU points\n";
}

void UnloadPointCloudRenderer(PointCloudRenderer& renderer) {
    if (renderer.vboId != 0) {
        rlUnloadVertexBuffer(renderer.vboId);
        renderer.vboId = 0;
    }
    if (renderer.vaoId != 0) {
        rlUnloadVertexArray(renderer.vaoId);
        renderer.vaoId = 0;
    }
    if (renderer.shader.id != 0) {
        UnloadShader(renderer.shader);
        renderer.shader = {};
    }
    renderer.pointCount = 0;
}

void UpdateProjectionForWindow(const Camera3D& camera) {
    const int screenHeight = std::max(GetScreenHeight(), 1);
    const float aspectRatio = static_cast<float>(GetScreenWidth()) / static_cast<float>(screenHeight);
    const Matrix projection = MatrixPerspective(camera.fovy * DEG2RAD, aspectRatio, kNearPlane, kFarPlane);
    rlSetMatrixProjection(projection);
}

void DrawPointCloudGPU(const PointCloudRenderer& renderer, float pointSize) {
    if (renderer.pointCount <= 0 || renderer.vboId == 0 || renderer.shader.id == 0) {
        return;
    }

    rlDrawRenderBatchActive();

    const Matrix mvp = MatrixMultiply(rlGetMatrixModelview(), rlGetMatrixProjection());
    rlEnableShader(renderer.shader.id);
    rlSetUniformMatrix(renderer.mvpLocation, mvp);

    if (renderer.vaoId != 0) {
        rlEnableVertexArray(renderer.vaoId);
    } else {
        rlEnableVertexBuffer(renderer.vboId);
        rlSetVertexAttribute(0, 3, RL_FLOAT, false, sizeof(GPUPoint), 0);
        rlEnableVertexAttribute(0);
        rlSetVertexAttribute(1, 4, RL_UNSIGNED_BYTE, true, sizeof(GPUPoint), 3 * static_cast<int>(sizeof(float)));
        rlEnableVertexAttribute(1);
    }

    glPointSize(pointSize);
    glDrawArrays(GL_POINTS, 0, renderer.pointCount);

    if (renderer.vaoId != 0) {
        rlDisableVertexArray();
    } else {
        rlDisableVertexAttribute(1);
        rlDisableVertexAttribute(0);
        rlDisableVertexBuffer();
    }

    rlDisableShader();
}

void RebuildAlignedCloud(ViewerState& state, PointCloudRenderer& renderer) {
    state.alignedPoints = state.sourcePoints;
    state.alignment = AlignPointCloudPCA(state.alignedPoints, state.enableAlignment);

    if (state.normalize) {
        ApplyRobustNormalization(state.alignedPoints);
    }

    std::cout
        << "[viewer] centered point cloud at centroid=("
        << state.alignment.centroid.x << ", "
        << state.alignment.centroid.y << ", "
        << state.alignment.centroid.z << ") "
        << "alignment=" << (state.enableAlignment ? "on" : "off") << " "
        << "normalize=" << (state.normalize ? "on" : "off") << '\n';

    RefreshPointCloudGPU(state, renderer);
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

    if (viewerState.sourcePoints.empty()) {
        std::cerr << "Warning: point cloud is empty.\n";
        return 1;
    }

    SetConfigFlags(FLAG_WINDOW_RESIZABLE | FLAG_MSAA_4X_HINT);
    InitWindow(1280, 720, "3D Viewer");
    MaximizeWindow();
    SetTargetFPS(60);

    const char* rendererName = reinterpret_cast<const char*>(glGetString(GL_RENDERER));
    std::cout << "Renderer: " << (rendererName != nullptr ? rendererName : "unknown") << '\n';

    PointCloudRenderer renderer;
    try {
        EnsureRendererShader(renderer);
        RebuildAlignedCloud(viewerState, renderer);
    } catch (const std::exception& error) {
        std::cerr << "Failed to initialize GPU point cloud renderer: " << error.what() << '\n';
        CloseWindow();
        return 1;
    }

    std::cout << "Loaded " << viewerState.sourcePoints.size() << " points from " << plyPath << '\n';

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
        if (IsKeyPressed(KEY_G)) {
            viewerState.showGrid = !viewerState.showGrid;
            std::cout << "[viewer] grid: " << (viewerState.showGrid ? "on" : "off") << "\n";
        }
        if (IsKeyPressed(KEY_F)) {
            for (Point& point : viewerState.alignedPoints) {
                point.y = -point.y;
            }

            RefreshPointCloudGPU(viewerState, renderer);
            std::printf("[viewer] flipped Y axis\n");
        }
        if (IsKeyPressed(KEY_U)) {
            viewerState.enableAlignment = !viewerState.enableAlignment;
            RebuildAlignedCloud(viewerState, renderer);
            ResetCameraState(cameraState, camera);
            std::cout << "[viewer] alignment " << (viewerState.enableAlignment ? "enabled" : "disabled") << '\n';
        }
        if (IsKeyPressed(KEY_N)) {
            viewerState.normalize = !viewerState.normalize;
            RebuildAlignedCloud(viewerState, renderer);
            std::cout << "[viewer] normalization " << (viewerState.normalize ? "enabled" : "disabled") << '\n';
        }
        if (IsKeyPressed(KEY_F11)) {
            ToggleFullscreen();
        }
        if (IsKeyPressed(KEY_EQUAL) || IsKeyPressed(KEY_KP_ADD)) {
            viewerState.pointSize = std::min(viewerState.pointSize + 1.0f, 10.0f);
        }
        if (IsKeyPressed(KEY_MINUS) || IsKeyPressed(KEY_KP_SUBTRACT)) {
            viewerState.pointSize = std::max(viewerState.pointSize - 1.0f, 1.0f);
        }

        const float aspectRatio = static_cast<float>(GetScreenWidth()) / static_cast<float>(std::max(GetScreenHeight(), 1));
        (void)aspectRatio;

        BeginDrawing();
        ClearBackground(BLACK);

        BeginMode3D(camera);
        UpdateProjectionForWindow(camera);
        if (viewerState.showGrid) DrawGrid(20, 0.1f);
        DrawPointCloudGPU(renderer, viewerState.pointSize);
        EndMode3D();

        DrawFPS(10, 10);
        DrawText(TextFormat("Points: %i / %i", static_cast<int>(viewerState.renderPoints.size()), static_cast<int>(viewerState.sourcePoints.size())), 10, 34, 20, RAYWHITE);
        DrawText(TextFormat("PCA: %s | Applied: %s", viewerState.alignment.classification, viewerState.alignment.alignmentApplied ? "yes" : "no"), 10, 58, 20, RAYWHITE);
        DrawText(TextFormat("Alignment: %s | Point Size: %.1f", viewerState.enableAlignment ? "ON" : "OFF", viewerState.pointSize), 10, 82, 20, RAYWHITE);
        DrawText("RMB look | WASD move | Wheel zoom | Q/E vertical | Shift fast | Ctrl slow", 10, 110, 20, RAYWHITE);
        DrawText(TextFormat("F flip Y | U align: %s | N normalize: %s | F11 fullscreen", viewerState.enableAlignment ? "ON" : "OFF", viewerState.normalize ? "ON" : "OFF"), 10, 134, 20, RAYWHITE);
        DrawText("G grid | R reset | +/- point size", 10, 158, 20, RAYWHITE);

        EndDrawing();
    }

    if (cameraState.isRotating) {
        EnableCursor();
    }

    UnloadPointCloudRenderer(renderer);
    CloseWindow();
    return 0;
}
