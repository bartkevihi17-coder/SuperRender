#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <dwmapi.h>
#include <d3d11.h>
#include <dxgi1_3.h>
#include <d3dcompiler.h>
#include <windows.graphics.capture.interop.h>
#include <windows.graphics.directx.direct3d11.interop.h>
#include <wrl/client.h>

#include <winrt/Windows.Foundation.h>
#include <winrt/Windows.Graphics.h>
#include <winrt/Windows.Graphics.Capture.h>
#include <winrt/Windows.Graphics.DirectX.h>
#include <winrt/Windows.Graphics.DirectX.Direct3D11.h>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <mutex>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

using Microsoft::WRL::ComPtr;
using namespace std::chrono;
namespace capture = winrt::Windows::Graphics::Capture;
namespace directx = winrt::Windows::Graphics::DirectX;
namespace direct3d11 = winrt::Windows::Graphics::DirectX::Direct3D11;

static constexpr wchar_t kWindowClass[] = L"SuperRender.ExternalFrameGen";
static constexpr UINT WM_SR_STOP = WM_APP + 41;

struct Options {
    DWORD gamePid = 0;
    DWORD ownerPid = 0;
    int targetFps = 60;
    int blockSize = 32;
    int searchRadius = 4;
    std::filesystem::path telemetry;
};

struct Params {
    uint32_t width;
    uint32_t height;
    uint32_t blockSize;
    uint32_t searchRadius;
    float factor;
    float costThreshold;
    float pad0;
    float pad1;
};
static_assert(sizeof(Params) == 32);

static const char* kShader = R"HLSL(
cbuffer Params : register(b0)
{
    uint Width;
    uint Height;
    uint BlockSize;
    uint SearchRadius;
    float Factor;
    float CostThreshold;
    float2 Padding;
};

Texture2D<float4> PrevTex : register(t0);
Texture2D<float4> CurrTex : register(t1);
StructuredBuffer<float4> MotionIn : register(t2);
RWStructuredBuffer<float4> MotionOut : register(u0);
RWTexture2D<float4> OutputTex : register(u1);
SamplerState LinearClamp : register(s0);

float3 SafeLoad(Texture2D<float4> tex, int2 p)
{
    p = clamp(p, int2(0, 0), int2((int)Width - 1, (int)Height - 1));
    return tex.Load(int3(p, 0)).rgb;
}

[numthreads(8, 8, 1)]
void Flow(uint3 tid : SV_DispatchThreadID)
{
    uint blocksX = (Width + BlockSize - 1) / BlockSize;
    uint blocksY = (Height + BlockSize - 1) / BlockSize;
    if (tid.x >= blocksX || tid.y >= blocksY) return;

    int2 origin = int2(tid.xy) * (int)BlockSize;
    int q = max(2, (int)BlockSize / 4);
    int h = max(2, (int)BlockSize / 2);
    int tq = max(2, (int)(BlockSize * 3 / 4));
    int2 samples[5] = {
        int2(h, h), int2(q, q), int2(tq, q), int2(q, tq), int2(tq, tq)
    };

    float bestCost = 1e20;
    int2 bestOffset = int2(0, 0);
    int r = (int)SearchRadius;

    for (int dy = -r; dy <= r; dy += 2)
    {
        for (int dx = -r; dx <= r; dx += 2)
        {
            float cost = 0.0;
            [unroll]
            for (int s = 0; s < 5; ++s)
            {
                int2 cp = origin + samples[s];
                cp = clamp(cp, int2(0, 0), int2((int)Width - 1, (int)Height - 1));
                int2 pp = cp + int2(dx, dy);
                float3 a = SafeLoad(CurrTex, cp);
                float3 b = SafeLoad(PrevTex, pp);
                float3 d = a - b;
                cost += dot(d, d);
            }
            cost *= 0.2;
            if (cost < bestCost)
            {
                bestCost = cost;
                bestOffset = int2(dx, dy);
            }
        }
    }

    uint index = tid.y * blocksX + tid.x;
    // bestOffset maps current -> previous. Store previous -> current.
    MotionOut[index] = float4(-(float)bestOffset.x, -(float)bestOffset.y, bestCost, 0.0);
}

float4 SampleLinear(Texture2D<float4> tex, float2 p)
{
    p = clamp(p, float2(0.0, 0.0), float2((float)Width - 1.0, (float)Height - 1.0));
    float2 uv = (p + 0.5) / float2((float)Width, (float)Height);
    return tex.SampleLevel(LinearClamp, uv, 0.0);
}

[numthreads(16, 16, 1)]
void Interpolate(uint3 tid : SV_DispatchThreadID)
{
    if (tid.x >= Width || tid.y >= Height) return;
    uint blocksX = (Width + BlockSize - 1) / BlockSize;
    uint2 block = min(tid.xy / BlockSize,
                      uint2(blocksX - 1, (Height + BlockSize - 1) / BlockSize - 1));
    float4 flow = MotionIn[block.y * blocksX + block.x];
    float2 motion = flow.xy;

    float2 p = float2(tid.xy);
    if (flow.z > CostThreshold)
    {
        float4 a0 = PrevTex.Load(int3(tid.xy, 0));
        float4 b0 = CurrTex.Load(int3(tid.xy, 0));
        OutputTex[tid.xy] = lerp(a0, b0, Factor);
        return;
    }

    float2 prevP = p - Factor * motion;
    float2 currP = p + (1.0 - Factor) * motion;
    float4 a = SampleLinear(PrevTex, prevP);
    float4 b = SampleLinear(CurrTex, currP);

    // Static/high-contrast UI naturally tends toward zero motion. This
    // confidence-weighted blend also avoids over-warping uncertain blocks.
    float confidence = saturate(1.0 - flow.z / max(CostThreshold, 0.0001));
    float4 warped = lerp(a, b, Factor);
    float4 plain = lerp(PrevTex.Load(int3(tid.xy, 0)),
                        CurrTex.Load(int3(tid.xy, 0)), Factor);
    OutputTex[tid.xy] = lerp(plain, warped, confidence);
}

[numthreads(16, 16, 1)]
void CopyCurrent(uint3 tid : SV_DispatchThreadID)
{
    if (tid.x >= Width || tid.y >= Height) return;
    OutputTex[tid.xy] = CurrTex.Load(int3(tid.xy, 0));
}
)HLSL";

static std::string Narrow(std::wstring const& input) {
    if (input.empty()) return {};
    int n = WideCharToMultiByte(CP_UTF8, 0, input.data(), (int)input.size(),
                                nullptr, 0, nullptr, nullptr);
    std::string out((size_t)n, '\0');
    WideCharToMultiByte(CP_UTF8, 0, input.data(), (int)input.size(),
                        out.data(), n, nullptr, nullptr);
    return out;
}

static std::wstring ErrorText(HRESULT hr) {
    wchar_t* message = nullptr;
    FormatMessageW(FORMAT_MESSAGE_ALLOCATE_BUFFER | FORMAT_MESSAGE_FROM_SYSTEM |
                       FORMAT_MESSAGE_IGNORE_INSERTS,
                   nullptr, (DWORD)hr, MAKELANGID(LANG_NEUTRAL, SUBLANG_DEFAULT),
                   (LPWSTR)&message, 0, nullptr);
    std::wstring result = message ? message : L"unknown error";
    if (message) LocalFree(message);
    return result;
}

static bool ProcessAlive(DWORD pid) {
    if (!pid) return false;
    HANDLE h = OpenProcess(SYNCHRONIZE, FALSE, pid);
    if (!h) return false;
    DWORD state = WaitForSingleObject(h, 0);
    CloseHandle(h);
    return state == WAIT_TIMEOUT;
}

struct WindowSearch {
    DWORD pid = 0;
    HWND best = nullptr;
    long long area = 0;
};

static BOOL CALLBACK EnumWindowProc(HWND hwnd, LPARAM lp) {
    auto* search = reinterpret_cast<WindowSearch*>(lp);
    DWORD pid = 0;
    GetWindowThreadProcessId(hwnd, &pid);
    if (pid != search->pid || !IsWindowVisible(hwnd) || GetWindow(hwnd, GW_OWNER))
        return TRUE;
    RECT r{};
    if (!GetWindowRect(hwnd, &r)) return TRUE;
    long long area = (long long)std::max(0L, r.right - r.left) *
                     (long long)std::max(0L, r.bottom - r.top);
    if (area > search->area) {
        search->area = area;
        search->best = hwnd;
    }
    return TRUE;
}

static HWND FindGameWindow(DWORD pid) {
    WindowSearch search{pid, nullptr, 0};
    EnumWindows(EnumWindowProc, reinterpret_cast<LPARAM>(&search));
    return search.best;
}

static LRESULT CALLBACK OverlayProc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp) {
    switch (msg) {
    case WM_NCHITTEST:
        return HTTRANSPARENT;
    case WM_MOUSEACTIVATE:
        return MA_NOACTIVATE;
    case WM_ERASEBKGND:
        return 1;
    case WM_SR_STOP:
    case WM_CLOSE:
        DestroyWindow(hwnd);
        return 0;
    case WM_DESTROY:
        PostQuitMessage(0);
        return 0;
    default:
        return DefWindowProcW(hwnd, msg, wp, lp);
    }
}

class ExternalFrameGen {
public:
    ExternalFrameGen(Options options, HWND source)
        : m_options(std::move(options)), m_source(source) {}

    ~ExternalFrameGen() {
        m_running = false;
        if (m_renderThread.joinable()) m_renderThread.join();
        try {
            if (m_pool && m_frameToken.value) m_pool.FrameArrived(m_frameToken);
        } catch (...) {}
        if (m_session) m_session.Close();
        if (m_pool) m_pool.Close();
        if (m_overlay && IsWindow(m_overlay)) DestroyWindow(m_overlay);
    }

    bool Initialize(std::wstring& error) {
        if (!capture::GraphicsCaptureSession::IsSupported()) {
            error = L"Windows Graphics Capture is not supported on this system.";
            return false;
        }

        UINT flags = D3D11_CREATE_DEVICE_BGRA_SUPPORT;
        D3D_FEATURE_LEVEL requested[] = {
            D3D_FEATURE_LEVEL_11_0, D3D_FEATURE_LEVEL_10_1, D3D_FEATURE_LEVEL_10_0
        };
        D3D_FEATURE_LEVEL got{};
        HRESULT hr = D3D11CreateDevice(
            nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr, flags,
            requested, ARRAYSIZE(requested), D3D11_SDK_VERSION,
            &m_device, &got, &m_context);
        if (FAILED(hr)) {
            error = L"D3D11CreateDevice failed: " + ErrorText(hr);
            return false;
        }

        ComPtr<IDXGIDevice> dxgiDevice;
        if (FAILED(m_device.As(&dxgiDevice))) {
            error = L"Could not obtain IDXGIDevice.";
            return false;
        }
        winrt::com_ptr<IInspectable> inspectable;
        hr = CreateDirect3D11DeviceFromDXGIDevice(dxgiDevice.Get(), inspectable.put());
        if (FAILED(hr)) {
            error = L"Could not create WinRT D3D device: " + ErrorText(hr);
            return false;
        }
        m_winrtDevice = inspectable.as<direct3d11::IDirect3DDevice>();

        auto interop = winrt::get_activation_factory<capture::GraphicsCaptureItem,
                                                     IGraphicsCaptureItemInterop>();
        capture::GraphicsCaptureItem item{nullptr};
        hr = interop->CreateForWindow(
            m_source,
            winrt::guid_of<capture::GraphicsCaptureItem>(),
            winrt::put_abi(item));
        if (FAILED(hr) || !item) {
            error = L"Could not create capture item for the game window.";
            return false;
        }
        m_item = item;
        auto size = item.Size();
        if (size.Width < 64 || size.Height < 64) {
            error = L"Game window is too small to capture.";
            return false;
        }
        m_width = (UINT)size.Width;
        m_height = (UINT)size.Height;

        if (!CreateOverlay(error) || !CreateResources(error) || !CompileShaders(error))
            return false;

        try {
            m_pool = capture::Direct3D11CaptureFramePool::CreateFreeThreaded(
                m_winrtDevice, directx::DirectXPixelFormat::B8G8R8A8UIntNormalized,
                3, size);
            m_frameToken = m_pool.FrameArrived(
                [this](capture::Direct3D11CaptureFramePool const& sender,
                       winrt::Windows::Foundation::IInspectable const&) {
                    OnFrame(sender);
                });
            m_session = m_pool.CreateCaptureSession(m_item);
            try { m_session.IsCursorCaptureEnabled(false); } catch (...) {}
            m_session.StartCapture();
        } catch (winrt::hresult_error const& ex) {
            error = L"Capture initialization failed: " + std::wstring(ex.message());
            return false;
        }

        m_running = true;
        WriteTelemetry("starting", 0, 0, 0, 0.0, 0.0);
        m_renderThread = std::thread([this] { RenderLoop(); });
        return true;
    }

    int RunMessageLoop() {
        MSG msg{};
        while (GetMessageW(&msg, nullptr, 0, 0) > 0) {
            TranslateMessage(&msg);
            DispatchMessageW(&msg);
        }
        m_running = false;
        return (int)msg.wParam;
    }

private:
    bool CreateOverlay(std::wstring& error) {
        HINSTANCE instance = GetModuleHandleW(nullptr);
        WNDCLASSEXW wc{sizeof(wc)};
        wc.lpfnWndProc = OverlayProc;
        wc.hInstance = instance;
        wc.hCursor = LoadCursorW(nullptr, IDC_ARROW);
        wc.lpszClassName = kWindowClass;
        RegisterClassExW(&wc);

        RECT rect{};
        GetWindowRect(m_source, &rect);
        int w = std::max(1L, rect.right - rect.left);
        int h = std::max(1L, rect.bottom - rect.top);
        m_overlay = CreateWindowExW(
            WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE,
            kWindowClass, L"SuperRender FrameGen", WS_POPUP,
            rect.left, rect.top, w, h, nullptr, nullptr, instance, nullptr);
        if (!m_overlay) {
            error = L"Could not create the external Frame Generation overlay.";
            return false;
        }
        SetWindowDisplayAffinity(m_overlay, WDA_EXCLUDEFROMCAPTURE);
        ShowWindow(m_overlay, SW_SHOWNOACTIVATE);
        SetWindowPos(m_overlay, HWND_TOPMOST, rect.left, rect.top, w, h,
                     SWP_NOACTIVATE | SWP_SHOWWINDOW);

        ComPtr<IDXGIDevice> dxgiDevice;
        m_device.As(&dxgiDevice);
        ComPtr<IDXGIAdapter> adapter;
        dxgiDevice->GetAdapter(&adapter);
        ComPtr<IDXGIFactory2> factory;
        adapter->GetParent(IID_PPV_ARGS(&factory));

        DXGI_SWAP_CHAIN_DESC1 desc{};
        desc.Width = m_width;
        desc.Height = m_height;
        desc.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
        desc.SampleDesc.Count = 1;
        desc.BufferUsage = DXGI_USAGE_RENDER_TARGET_OUTPUT;
        desc.BufferCount = 2;
        desc.SwapEffect = DXGI_SWAP_EFFECT_FLIP_DISCARD;
        desc.Scaling = DXGI_SCALING_STRETCH;
        desc.AlphaMode = DXGI_ALPHA_MODE_IGNORE;
        HRESULT hr = factory->CreateSwapChainForHwnd(
            m_device.Get(), m_overlay, &desc, nullptr, nullptr, &m_swapChain);
        if (FAILED(hr)) {
            error = L"Could not create output swap chain: " + ErrorText(hr);
            return false;
        }
        factory->MakeWindowAssociation(m_overlay, DXGI_MWA_NO_ALT_ENTER);
        hr = m_swapChain->GetBuffer(0, IID_PPV_ARGS(&m_swapBuffer));
        if (FAILED(hr)) {
            error = L"Could not access output back buffer.";
            return false;
        }
        return true;
    }

    bool CreateResources(std::wstring& error) {
        D3D11_TEXTURE2D_DESC input{};
        input.Width = m_width;
        input.Height = m_height;
        input.MipLevels = 1;
        input.ArraySize = 1;
        input.Format = DXGI_FORMAT_B8G8R8A8_UNORM;
        input.SampleDesc.Count = 1;
        input.Usage = D3D11_USAGE_DEFAULT;
        input.BindFlags = D3D11_BIND_SHADER_RESOURCE;
        HRESULT hr = m_device->CreateTexture2D(&input, nullptr, &m_prev);
        if (FAILED(hr)) { error = L"Could not create previous-frame texture."; return false; }
        hr = m_device->CreateTexture2D(&input, nullptr, &m_curr);
        if (FAILED(hr)) { error = L"Could not create current-frame texture."; return false; }
        m_device->CreateShaderResourceView(m_prev.Get(), nullptr, &m_prevSrv);
        m_device->CreateShaderResourceView(m_curr.Get(), nullptr, &m_currSrv);

        D3D11_TEXTURE2D_DESC output = input;
        output.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
        output.BindFlags = D3D11_BIND_UNORDERED_ACCESS | D3D11_BIND_SHADER_RESOURCE;
        hr = m_device->CreateTexture2D(&output, nullptr, &m_output);
        if (FAILED(hr)) { error = L"Could not create generated-frame texture."; return false; }
        hr = m_device->CreateUnorderedAccessView(m_output.Get(), nullptr, &m_outputUav);
        if (FAILED(hr)) { error = L"GPU does not support the required output UAV."; return false; }

        m_blocksX = (m_width + m_options.blockSize - 1) / m_options.blockSize;
        m_blocksY = (m_height + m_options.blockSize - 1) / m_options.blockSize;
        UINT elements = m_blocksX * m_blocksY;
        D3D11_BUFFER_DESC motion{};
        motion.ByteWidth = elements * 16;
        motion.Usage = D3D11_USAGE_DEFAULT;
        motion.BindFlags = D3D11_BIND_SHADER_RESOURCE | D3D11_BIND_UNORDERED_ACCESS;
        motion.MiscFlags = D3D11_RESOURCE_MISC_BUFFER_STRUCTURED;
        motion.StructureByteStride = 16;
        hr = m_device->CreateBuffer(&motion, nullptr, &m_motion);
        if (FAILED(hr)) { error = L"Could not create motion buffer."; return false; }

        D3D11_SHADER_RESOURCE_VIEW_DESC srv{};
        srv.Format = DXGI_FORMAT_UNKNOWN;
        srv.ViewDimension = D3D11_SRV_DIMENSION_BUFFER;
        srv.Buffer.NumElements = elements;
        hr = m_device->CreateShaderResourceView(m_motion.Get(), &srv, &m_motionSrv);
        if (FAILED(hr)) { error = L"Could not create motion SRV."; return false; }

        D3D11_UNORDERED_ACCESS_VIEW_DESC uav{};
        uav.Format = DXGI_FORMAT_UNKNOWN;
        uav.ViewDimension = D3D11_UAV_DIMENSION_BUFFER;
        uav.Buffer.NumElements = elements;
        hr = m_device->CreateUnorderedAccessView(m_motion.Get(), &uav, &m_motionUav);
        if (FAILED(hr)) { error = L"Could not create motion UAV."; return false; }

        D3D11_BUFFER_DESC cbd{};
        cbd.ByteWidth = sizeof(Params);
        cbd.Usage = D3D11_USAGE_DYNAMIC;
        cbd.BindFlags = D3D11_BIND_CONSTANT_BUFFER;
        cbd.CPUAccessFlags = D3D11_CPU_ACCESS_WRITE;
        hr = m_device->CreateBuffer(&cbd, nullptr, &m_params);
        if (FAILED(hr)) { error = L"Could not create Frame Generation constants."; return false; }

        D3D11_SAMPLER_DESC samp{};
        samp.Filter = D3D11_FILTER_MIN_MAG_MIP_LINEAR;
        samp.AddressU = D3D11_TEXTURE_ADDRESS_CLAMP;
        samp.AddressV = D3D11_TEXTURE_ADDRESS_CLAMP;
        samp.AddressW = D3D11_TEXTURE_ADDRESS_CLAMP;
        hr = m_device->CreateSamplerState(&samp, &m_sampler);
        if (FAILED(hr)) { error = L"Could not create interpolation sampler."; return false; }
        return true;
    }

    bool CompileOne(char const* entry, ComPtr<ID3D11ComputeShader>& out,
                    std::wstring& error) {
        UINT flags = D3DCOMPILE_ENABLE_STRICTNESS | D3DCOMPILE_OPTIMIZATION_LEVEL3;
        ComPtr<ID3DBlob> code, errors;
        HRESULT hr = D3DCompile(kShader, strlen(kShader), "SuperRenderFrameGen",
                                nullptr, nullptr, entry, "cs_5_0", flags, 0,
                                &code, &errors);
        if (FAILED(hr)) {
            std::string message;
            if (errors) message.assign((char*)errors->GetBufferPointer(), errors->GetBufferSize());
            error = L"Shader compilation failed: " +
                    std::wstring(message.begin(), message.end());
            return false;
        }
        hr = m_device->CreateComputeShader(
            code->GetBufferPointer(), code->GetBufferSize(), nullptr, &out);
        if (FAILED(hr)) {
            error = L"GPU rejected a Frame Generation compute shader.";
            return false;
        }
        return true;
    }

    bool CompileShaders(std::wstring& error) {
        return CompileOne("Flow", m_flowCs, error) &&
               CompileOne("Interpolate", m_interpCs, error) &&
               CompileOne("CopyCurrent", m_copyCs, error);
    }

    void UpdateParams(float factor) {
        D3D11_MAPPED_SUBRESOURCE mapped{};
        if (SUCCEEDED(m_context->Map(m_params.Get(), 0, D3D11_MAP_WRITE_DISCARD, 0, &mapped))) {
            auto* p = reinterpret_cast<Params*>(mapped.pData);
            p->width = m_width;
            p->height = m_height;
            p->blockSize = (uint32_t)m_options.blockSize;
            p->searchRadius = (uint32_t)m_options.searchRadius;
            p->factor = factor;
            p->costThreshold = 0.16f;
            p->pad0 = p->pad1 = 0.0f;
            m_context->Unmap(m_params.Get(), 0);
        }
    }

    void Unbind() {
        ID3D11ShaderResourceView* nullSrv[3] = {};
        ID3D11UnorderedAccessView* nullUav[2] = {};
        m_context->CSSetShaderResources(0, 3, nullSrv);
        m_context->CSSetUnorderedAccessViews(0, 2, nullUav, nullptr);
        m_context->CSSetShader(nullptr, nullptr, 0);
    }

    void DispatchFlow() {
        UpdateParams(0.0f);
        ID3D11ShaderResourceView* srvs[2] = {m_prevSrv.Get(), m_currSrv.Get()};
        ID3D11UnorderedAccessView* uavs[1] = {m_motionUav.Get()};
        m_context->CSSetShader(m_flowCs.Get(), nullptr, 0);
        m_context->CSSetConstantBuffers(0, 1, m_params.GetAddressOf());
        m_context->CSSetShaderResources(0, 2, srvs);
        m_context->CSSetUnorderedAccessViews(0, 1, uavs, nullptr);
        m_context->Dispatch((m_blocksX + 7) / 8, (m_blocksY + 7) / 8, 1);
        Unbind();
    }

    void DispatchFrame(float factor, bool interpolate) {
        UpdateParams(factor);
        ID3D11ShaderResourceView* srvs[3] = {
            m_prevSrv.Get(), m_currSrv.Get(), m_motionSrv.Get()
        };
        ID3D11UnorderedAccessView* uavs[2] = {nullptr, m_outputUav.Get()};
        m_context->CSSetShader(interpolate ? m_interpCs.Get() : m_copyCs.Get(), nullptr, 0);
        m_context->CSSetConstantBuffers(0, 1, m_params.GetAddressOf());
        m_context->CSSetShaderResources(0, 3, srvs);
        m_context->CSSetUnorderedAccessViews(0, 2, uavs, nullptr);
        m_context->CSSetSamplers(0, 1, m_sampler.GetAddressOf());
        m_context->Dispatch((m_width + 15) / 16, (m_height + 15) / 16, 1);
        Unbind();
    }

    void OnFrame(capture::Direct3D11CaptureFramePool const& sender) {
        try {
            auto frame = sender.TryGetNextFrame();
            if (!frame || !m_running) return;
            auto size = frame.ContentSize();
            if ((UINT)size.Width != m_width || (UINT)size.Height != m_height) {
                // A resolution change is rare during a session. Restarting the
                // helper is safer than presenting mismatched resources.
                m_resizeDetected = true;
                return;
            }
            auto access = frame.Surface().as<IDirect3DDxgiInterfaceAccess>();
            winrt::com_ptr<ID3D11Texture2D> texture;
            winrt::check_hresult(access->GetInterface(
                __uuidof(ID3D11Texture2D), texture.put_void()));

            D3D11_TEXTURE2D_DESC desc{};
            texture->GetDesc(&desc);
            if (desc.Width != m_width || desc.Height != m_height ||
                desc.Format != DXGI_FORMAT_B8G8R8A8_UNORM) return;

            auto now = steady_clock::now();
            std::scoped_lock lock(m_gpuMutex);
            if (!m_haveCurrent) {
                m_context->CopyResource(m_curr.Get(), texture.get());
                m_context->CopyResource(m_prev.Get(), texture.get());
                m_prevTime = m_currTime = now;
                m_haveCurrent = true;
                m_havePair = false;
            } else {
                std::swap(m_prev, m_curr);
                std::swap(m_prevSrv, m_currSrv);
                m_context->CopyResource(m_curr.Get(), texture.get());
                m_prevTime = m_currTime;
                m_currTime = now;
                DispatchFlow();
                m_havePair = true;
            }
            ++m_captureCount;
        } catch (...) {
            // One bad frame must not kill the game or the helper.
        }
    }

    void MoveOverlay() {
        RECT rect{};
        if (!GetWindowRect(m_source, &rect)) return;
        int w = std::max(1L, rect.right - rect.left);
        int h = std::max(1L, rect.bottom - rect.top);
        SetWindowPos(m_overlay, HWND_TOPMOST, rect.left, rect.top, w, h,
                     SWP_NOACTIVATE | SWP_SHOWWINDOW);
    }

    void RenderLoop() {
        using clock = steady_clock;
        const double fps = std::clamp((double)m_options.targetFps, 30.0, 240.0);
        const auto period = duration<double>(1.0 / fps);
        auto next = clock::now();
        auto statsAt = next;
        auto overlayAt = next;
        uint64_t lastCapture = 0, lastPresent = 0, lastGenerated = 0;

        while (m_running && ProcessAlive(m_options.gamePid) &&
               (!m_options.ownerPid || ProcessAlive(m_options.ownerPid))) {
            auto tickStart = clock::now();
            if (m_resizeDetected) break;

            bool generated = false;
            {
                std::scoped_lock lock(m_gpuMutex);
                if (m_haveCurrent) {
                    float factor = 1.0f;
                    bool interpolate = false;
                    if (m_havePair) {
                        double dt = duration<double>(m_currTime - m_prevTime).count();
                        dt = std::clamp(dt, 1.0 / 240.0, 0.12);
                        double elapsed = duration<double>(tickStart - m_currTime).count();
                        factor = (float)std::clamp(elapsed / dt, 0.0, 1.0);
                        interpolate = factor > 0.015f && factor < 0.985f;
                    }
                    auto gpuStart = clock::now();
                    DispatchFrame(factor, interpolate);
                    m_context->CopyResource(m_swapBuffer.Get(), m_output.Get());
                    HRESULT hr = m_swapChain->Present(0, 0);
                    m_lastEngineMs = (float)(duration<double, std::milli>(
                        clock::now() - gpuStart).count());
                    if (SUCCEEDED(hr)) {
                        ++m_presentCount;
                        if (interpolate) {
                            ++m_generatedCount;
                            generated = true;
                        }
                    }
                }
            }

            auto now = clock::now();
            if (now - overlayAt >= milliseconds(500)) {
                MoveOverlay();
                overlayAt = now;
            }
            if (now - statsAt >= seconds(1)) {
                double secondsElapsed = duration<double>(now - statsAt).count();
                uint64_t captures = m_captureCount.load();
                uint64_t presents = m_presentCount.load();
                uint64_t generatedFrames = m_generatedCount.load();
                double captureFps = (captures - lastCapture) / secondsElapsed;
                double presentFps = (presents - lastPresent) / secondsElapsed;
                double generatedFps = (generatedFrames - lastGenerated) / secondsElapsed;
                double latency = 0.0;
                if (m_havePair) {
                    latency = 1000.0 * std::clamp(
                        duration<double>(m_currTime - m_prevTime).count(),
                        1.0 / 240.0, 0.12);
                }
                WriteTelemetry("active", captureFps, presentFps, generatedFps,
                               latency, m_lastEngineMs.load());
                lastCapture = captures;
                lastPresent = presents;
                lastGenerated = generatedFrames;
                statsAt = now;
            }

            next += duration_cast<clock::duration>(period);
            auto current = clock::now();
            if (next < current - milliseconds(50)) next = current;
            std::this_thread::sleep_until(next);
        }

        WriteTelemetry(m_resizeDetected ? "resize" : "stopped", 0, 0, 0, 0, 0);
        m_running = false;
        if (m_overlay) PostMessageW(m_overlay, WM_SR_STOP, 0, 0);
    }

    void WriteTelemetry(char const* status, double captureFps, double presentFps,
                        double generatedFps, double latencyMs, double engineMs) {
        if (m_options.telemetry.empty()) return;
        std::error_code ec;
        std::filesystem::create_directories(m_options.telemetry.parent_path(), ec);
        auto tmp = m_options.telemetry;
        tmp += L".tmp";
        std::ofstream out(tmp, std::ios::trunc);
        if (!out) return;
        out.setf(std::ios::fixed);
        out.precision(2);
        out << "{\n"
            << "  \"status\": \"" << status << "\",\n"
            << "  \"backend\": \"external-wgc-d3d11\",\n"
            << "  \"capture_fps\": " << captureFps << ",\n"
            << "  \"presented_fps\": " << presentFps << ",\n"
            << "  \"generated_fps\": " << generatedFps << ",\n"
            << "  \"latency_ms\": " << latencyMs << ",\n"
            << "  \"engine_ms\": " << engineMs << ",\n"
            << "  \"width\": " << m_width << ",\n"
            << "  \"height\": " << m_height << ",\n"
            << "  \"block_size\": " << m_options.blockSize << ",\n"
            << "  \"search_radius\": " << m_options.searchRadius << "\n"
            << "}\n";
        out.close();
        std::filesystem::rename(tmp, m_options.telemetry, ec);
        if (ec) {
            std::filesystem::remove(m_options.telemetry, ec);
            ec.clear();
            std::filesystem::rename(tmp, m_options.telemetry, ec);
        }
    }

private:
    Options m_options;
    HWND m_source = nullptr;
    HWND m_overlay = nullptr;
    UINT m_width = 0, m_height = 0, m_blocksX = 0, m_blocksY = 0;

    ComPtr<ID3D11Device> m_device;
    ComPtr<ID3D11DeviceContext> m_context;
    direct3d11::IDirect3DDevice m_winrtDevice{nullptr};

    capture::GraphicsCaptureItem m_item{nullptr};
    capture::Direct3D11CaptureFramePool m_pool{nullptr};
    capture::GraphicsCaptureSession m_session{nullptr};
    winrt::event_token m_frameToken{};

    ComPtr<IDXGISwapChain1> m_swapChain;
    ComPtr<ID3D11Texture2D> m_swapBuffer;
    ComPtr<ID3D11Texture2D> m_prev, m_curr, m_output;
    ComPtr<ID3D11ShaderResourceView> m_prevSrv, m_currSrv, m_motionSrv;
    ComPtr<ID3D11UnorderedAccessView> m_outputUav, m_motionUav;
    ComPtr<ID3D11Buffer> m_motion, m_params;
    ComPtr<ID3D11SamplerState> m_sampler;
    ComPtr<ID3D11ComputeShader> m_flowCs, m_interpCs, m_copyCs;

    std::mutex m_gpuMutex;
    std::thread m_renderThread;
    std::atomic<bool> m_running{false};
    std::atomic<bool> m_resizeDetected{false};
    bool m_haveCurrent = false;
    bool m_havePair = false;
    steady_clock::time_point m_prevTime{}, m_currTime{};

    std::atomic<uint64_t> m_captureCount{0};
    std::atomic<uint64_t> m_presentCount{0};
    std::atomic<uint64_t> m_generatedCount{0};
    std::atomic<float> m_lastEngineMs{0.0f};
};

static bool ParseOptions(int argc, wchar_t** argv, Options& out) {
    for (int i = 1; i < argc; ++i) {
        std::wstring arg = argv[i];
        auto next = [&]() -> wchar_t* {
            return (i + 1 < argc) ? argv[++i] : nullptr;
        };
        if (arg == L"--pid") {
            if (auto v = next()) out.gamePid = wcstoul(v, nullptr, 10);
        } else if (arg == L"--owner-pid") {
            if (auto v = next()) out.ownerPid = wcstoul(v, nullptr, 10);
        } else if (arg == L"--target-fps") {
            if (auto v = next()) out.targetFps = _wtoi(v);
        } else if (arg == L"--block-size") {
            if (auto v = next()) out.blockSize = _wtoi(v);
        } else if (arg == L"--search-radius") {
            if (auto v = next()) out.searchRadius = _wtoi(v);
        } else if (arg == L"--telemetry") {
            if (auto v = next()) out.telemetry = v;
        }
    }
    out.targetFps = std::clamp(out.targetFps, 30, 240);
    out.blockSize = std::clamp(out.blockSize, 8, 64);
    // Keep an even radius because the lightweight search advances by 2 pixels.
    out.searchRadius = std::clamp(out.searchRadius, 2, 24);
    if (out.searchRadius & 1) ++out.searchRadius;
    return out.gamePid != 0;
}

static void WriteEarlyError(Options const& options, std::wstring const& message) {
    if (options.telemetry.empty()) return;
    std::error_code ec;
    std::filesystem::create_directories(options.telemetry.parent_path(), ec);
    std::ofstream out(options.telemetry, std::ios::trunc);
    if (!out) return;
    std::string msg = Narrow(message);
    for (char& c : msg) if (c == '"' || c == '\n' || c == '\r') c = ' ';
    out << "{\"status\":\"error\",\"message\":\"" << msg << "\"}\n";
}

int WINAPI wWinMain(HINSTANCE, HINSTANCE, PWSTR, int) {
    winrt::init_apartment(winrt::apartment_type::multi_threaded);

    int argc = 0;
    wchar_t** argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    Options options;
    bool valid = argv && ParseOptions(argc, argv, options);
    if (argv) LocalFree(argv);
    if (!valid) return 2;

    HWND gameWindow = nullptr;
    for (int i = 0; i < 100 && ProcessAlive(options.gamePid); ++i) {
        gameWindow = FindGameWindow(options.gamePid);
        if (gameWindow) break;
        Sleep(100);
    }
    if (!gameWindow) {
        WriteEarlyError(options, L"Could not find the visible game window.");
        return 3;
    }

    std::wstring error;
    try {
        ExternalFrameGen engine(options, gameWindow);
        if (!engine.Initialize(error)) {
            WriteEarlyError(options, error);
            return 4;
        }
        return engine.RunMessageLoop();
    } catch (winrt::hresult_error const& ex) {
        WriteEarlyError(options, std::wstring(ex.message()));
        return 5;
    } catch (...) {
        WriteEarlyError(options, L"Unexpected external Frame Generation error.");
        return 6;
    }
}
