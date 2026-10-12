#include <windows.h>
#include <shellapi.h>
#include <dwmapi.h>
#include <d3d11.h>
#include <dxgi1_3.h>
#include <dxgi1_2.h>
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
#include <array>
#include <deque>
#include <numeric>
#include <iomanip>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <mutex>
#include <sstream>
#include <string>
#include <thread>
#include <vector>
#include <utility>

using Microsoft::WRL::ComPtr;
using namespace std::chrono;
namespace capture = winrt::Windows::Graphics::Capture;
namespace directx = winrt::Windows::Graphics::DirectX;
namespace direct3d11 = winrt::Windows::Graphics::DirectX::Direct3D11;

// Some Windows SDK revisions do not expose this desktop interop interface
// as a C++ symbol even though the ABI is available. Declare its documented
// IUnknown contract locally instead of depending on SDK-specific aliases.
struct __declspec(uuid("A9B3D012-3DF2-4EE3-B8D1-8695F457D3C1"))
IDirect3DDxgiInterfaceAccess : IUnknown {
    virtual HRESULT STDMETHODCALLTYPE GetInterface(REFIID iid, void** object) = 0;
};

static constexpr wchar_t kWindowClass[] = L"SuperRender.ExternalFrameGen";
static constexpr UINT WM_SR_STOP = WM_APP + 41;

struct Options {
    DWORD gamePid = 0;
    DWORD ownerPid = 0;
    int targetFps = 60;
    int blockSize = 32;
    int searchRadius = 4;
    int pyramidLevels = 2;
    float dirtyThreshold = 0.025f;
    float earlyExitThreshold = 0.018f;
    int debugView = 0;
    float occlusionThreshold = 0.20f;
    float hudThreshold = 0.035f;
    std::filesystem::path telemetry;
    std::filesystem::path csv;
    std::filesystem::path benchmarkOutput;
    int benchmarkSeconds = 0;
    double minBaseFps = 20.0;
    double budgetFraction = 0.25;
    int gpuPriority = -2;
};

struct Params {
    uint32_t width;
    uint32_t height;
    uint32_t blockSize;
    uint32_t searchRadius;
    float factor;
    float costThreshold;
    float dirtyThreshold;
    float earlyExitThreshold;
    float occlusionThreshold;
    float hudThreshold;
    uint32_t debugView;
    float padding;
};
static_assert(sizeof(Params) == 48);

static const char* kShader = R"HLSL(
cbuffer Params : register(b0)
{
    uint Width;
    uint Height;
    uint BlockSize;
    uint SearchRadius;
    float Factor;
    float CostThreshold;
    float DirtyThreshold;
    float EarlyExitThreshold;
    float OcclusionThreshold;
    float HudThreshold;
    uint DebugView;
    float ParamsPadding;
};

Texture2D<float4> PrevTex : register(t0);
Texture2D<float4> CurrTex : register(t1);
StructuredBuffer<float4> MotionIn : register(t2);
RWStructuredBuffer<float4> MotionOut : register(u0);
RWTexture2D<float4> OutputTex : register(u1);
SamplerState LinearClamp : register(s0);


Texture2D<float> PrevLuma : register(t3);
Texture2D<float> CurrLuma : register(t4);
StructuredBuffer<float4> PreviousMotion : register(t5);
RWTexture2D<float> LumaOut : register(u2);
Texture2D<float> HudHistory : register(t7);
RWTexture2D<float> HudNext : register(u5);
StructuredBuffer<float4> RawMotion : register(t6);
RWStructuredBuffer<float4> FilteredMotion : register(u3);
RWTexture2D<float> ConfidenceOut : register(u4);

float Median3(float a,float b,float c)
{
    return max(min(a,b),min(max(a,b),c));
}

[numthreads(8,8,1)]
void FilterMotion(uint3 id : SV_DispatchThreadID)
{
    uint nx=(Width+BlockSize-1)/BlockSize;
    uint ny=(Height+BlockSize-1)/BlockSize;
    if(id.x>=nx || id.y>=ny) return;
    uint k=id.y*nx+id.x;
    float4 center=RawMotion[k];
    float4 left=RawMotion[id.y*nx+(id.x>0?id.x-1:id.x)];
    float4 right=RawMotion[id.y*nx+min(id.x+1,nx-1)];
    float4 up=RawMotion[(id.y>0?id.y-1:id.y)*nx+id.x];
    float4 down=RawMotion[min(id.y+1,ny-1)*nx+id.x];
    float2 median=float2(
      Median3(Median3(left.x,center.x,right.x),up.x,down.x),
      Median3(Median3(left.y,center.y,right.y),up.y,down.y));
    float disagreement=length(center.xy-median)/max((float)BlockSize,1.0);
    float confidence=saturate(center.w * (1.0-saturate(disagreement)));
    float2 vector=lerp(median,center.xy,confidence);
    FilteredMotion[k]=float4(vector,center.z,confidence);
    ConfidenceOut[id.xy]=confidence;
}


[numthreads(8,8,1)]
void LumaDownsample(uint3 id : SV_DispatchThreadID)
{
    uint w, h;
    LumaOut.GetDimensions(w, h);
    if (id.x >= w || id.y >= h) return;
    uint2 p = id.xy * 2;
    float3 a = CurrTex.Load(int3(min(p, uint2(Width-1,Height-1)),0)).rgb;
    float3 b = CurrTex.Load(int3(min(p+uint2(1,0), uint2(Width-1,Height-1)),0)).rgb;
    float3 c = CurrTex.Load(int3(min(p+uint2(0,1), uint2(Width-1,Height-1)),0)).rgb;
    float3 d = CurrTex.Load(int3(min(p+uint2(1,1), uint2(Width-1,Height-1)),0)).rgb;
    LumaOut[id.xy] = dot((a+b+c+d)*0.25, float3(0.2126,0.7152,0.0722));
}

[numthreads(8,8,1)]
void LumaQuarter(uint3 id : SV_DispatchThreadID)
{
    uint w,h;
    LumaOut.GetDimensions(w,h);
    if(id.x>=w || id.y>=h) return;
    uint sw,sh;
    CurrLuma.GetDimensions(sw,sh);
    uint2 p = id.xy*2;
    float v = 0;
    [unroll] for(uint j=0;j<2;++j)
      [unroll] for(uint i=0;i<2;++i)
        v += CurrLuma.Load(int3(min(p+uint2(i,j),uint2(sw-1,sh-1)),0));
    LumaOut[id.xy]=v*0.25;
}

// Quarter-resolution diamond search, followed by an explicit +/-1-pixel
// refinement. Each thread owns one independent block; no inter-group barriers.
float LumaCost(int2 origin, int2 offset, int2 dims)
{
    float sad=0;
    [unroll] for(int j=0;j<4;++j)
      [unroll] for(int i=0;i<4;++i)
      {
        int2 pos=clamp(origin+int2(i*2,j*2),int2(0,0),dims-1);
        int2 other=clamp(pos+offset,int2(0,0),dims-1);
        sad += abs(CurrLuma.Load(int3(pos,0))-PrevLuma.Load(int3(other,0)));
      }
    return sad*(1.0/16.0);
}
[numthreads(8,8,1)]
void Flow(uint3 tid : SV_DispatchThreadID)
{
    uint blocksX=(Width+BlockSize-1)/BlockSize;
    uint blocksY=(Height+BlockSize-1)/BlockSize;
    if(tid.x>=blocksX || tid.y>=blocksY) return;
    uint index=tid.y*blocksX+tid.x;
    uint w,h; CurrLuma.GetDimensions(w,h);
    int2 dims=int2(w,h);
    int2 origin=int2(tid.xy)*int(BlockSize/4);
    origin=clamp(origin,int2(0,0),dims-1);
    float dirty=LumaCost(origin,int2(0,0),dims);
    if(dirty<DirtyThreshold) {
        MotionOut[index]=float4(0,0,0,1);
        return;
    }
    float2 old=PreviousMotion[index].xy;
    int2 best=int2(round(-old/4.0));
    int r=max(1,int(SearchRadius/4));
    best=clamp(best,int2(-r,-r),int2(r,r));
    float score=LumaCost(origin,best,dims);
    if(score>EarlyExitThreshold) {
        // Coarse-to-fine diamond steps; avoid exhaustive 2D search.
        for(int step=max(1,r/2);step>=1;step/=2) {
            int2 offsets[4]={int2(step,0),int2(-step,0),
                             int2(0,step),int2(0,-step)};
            [unroll] for(int c=0;c<4;++c) {
                int2 trial=clamp(best+offsets[c],int2(-r,-r),int2(r,r));
                float cost=LumaCost(origin,trial,dims);
                if(cost<score){ score=cost; best=trial; }
            }
            if(step==1) break;
        }
        [unroll] for(int y=-1;y<=1;++y)
          [unroll] for(int x=-1;x<=1;++x) {
            int2 trial=clamp(best+int2(x,y),int2(-r,-r),int2(r,r));
            float cost=LumaCost(origin,trial,dims);
            if(cost<score){score=cost;best=trial;}
          }
    }
    // Motion is stored previous -> current, in full-resolution pixels.
    float confidence=saturate(1.0-score/max(EarlyExitThreshold*8.0,0.0001));
    MotionOut[index]=float4(-float2(best)*4.0, score, confidence);
}

float4 SampleLinear(Texture2D<float4> tex, float2 p)
{
    float2 uv = (p + 0.5) / float2((float)Width, (float)Height);
    return tex.SampleLevel(LinearClamp, uv, 0.0);
}

float4 DenseFlow(float2 p)
{
    uint nx=(Width+BlockSize-1)/BlockSize;
    uint ny=(Height+BlockSize-1)/BlockSize;
    // Bilinear interpolation between block centres. Edge clamping is explicit.
    float2 g=p/max(float(BlockSize),1.0)-0.5;
    int2 lo=int2(floor(g));
    float2 f=frac(g);
    int2 a=clamp(lo,int2(0,0),int2((int)nx-1,(int)ny-1));
    int2 b=clamp(lo+int2(1,0),int2(0,0),int2((int)nx-1,(int)ny-1));
    int2 c=clamp(lo+int2(0,1),int2(0,0),int2((int)nx-1,(int)ny-1));
    int2 d=clamp(lo+int2(1,1),int2(0,0),int2((int)nx-1,(int)ny-1));
    float4 v0=lerp(MotionIn[a.y*nx+a.x],MotionIn[b.y*nx+b.x],f.x);
    float4 v1=lerp(MotionIn[c.y*nx+c.x],MotionIn[d.y*nx+d.x],f.x);
    return lerp(v0,v1,f.y);
}

float3 HeatColor(float value)
{
    return saturate(float3(2.0-2.0*value,2.0*value,0.25));
}

[numthreads(16,16,1)]
void UpdateHud(uint3 id : SV_DispatchThreadID)
{
    if(id.x>=Width || id.y>=Height) return;
    float3 a=PrevTex.Load(int3(id.xy,0)).rgb;
    float3 b=CurrTex.Load(int3(id.xy,0)).rgb;
    float diff=dot(abs(a-b),float3(0.2126,0.7152,0.0722));
    float old=HudHistory.Load(int3(id.xy,0));
    // EMA of static persistence (not a classifier of actual HUD semantics).
    float staticNow=1.0-saturate(diff/max(HudThreshold,0.0001));
    HudNext[id.xy]=lerp(old,staticNow,0.06);
}

[numthreads(16,16,1)]
void Interpolate(uint3 tid : SV_DispatchThreadID)
{
    if(tid.x>=Width || tid.y>=Height) return;
    float2 p=float2(tid.xy);
    float4 flow=DenseFlow(p);
    float2 motion=flow.xy;
    float confidence=saturate(flow.w);
    float4 rawA=PrevTex.Load(int3(tid.xy,0));
    float4 rawB=CurrTex.Load(int3(tid.xy,0));
    float4 nearest=Factor<0.5?rawA:rawB;
    float4 plain=lerp(rawA,rawB,Factor);
    float persistence=HudHistory.Load(int3(tid.xy,0));

    if(DebugView==1) {
        OutputTex[tid.xy]=float4(HeatColor(confidence),1);
        return;
    }
    if(DebugView==2) {
        OutputTex[tid.xy]=float4(saturate(0.5+motion/max(float(BlockSize),1.0)*0.5),
                                confidence,1);
        return;
    }
    float2 pa=p-Factor*motion;
    float2 pb=p+(1.0-Factor)*motion;
    bool outside=any(pa<0.0)||any(pb<0.0)||
                 any(pa>float2(Width-1,Height-1))||
                 any(pb>float2(Width-1,Height-1));
    if(outside) { OutputTex[tid.xy]=nearest; return; }

    // Hard reject unreliable vectors and small fast objects.
    if(confidence<0.15 || (flow.z>EarlyExitThreshold*5.0 && confidence<0.45)) {
        OutputTex[tid.xy]=nearest;
        return;
    }
    float4 a=SampleLinear(PrevTex,pa);
    float4 b=SampleLinear(CurrTex,pb);
    float disagreement=dot(abs(a.rgb-b.rgb),float3(0.2126,0.7152,0.0722));
    float4 warped=lerp(a,b,Factor);
    if(disagreement>OcclusionThreshold) {
        // Single-sided candidate based on similarity to an observed endpoint.
        float costA=dot(abs(a.rgb-rawB.rgb),float3(0.2126,0.7152,0.0722));
        float costB=dot(abs(b.rgb-rawA.rgb),float3(0.2126,0.7152,0.0722));
        warped=costA<costB?a:b;
        confidence*=0.45;
    }
    // Avoid bilinear ghosting in uncertain areas.
    float4 fallback=confidence<0.5?nearest:plain;
    float strength=saturate((confidence-0.15)/0.55);
    if(persistence>0.9) strength=0;
    OutputTex[tid.xy]=lerp(fallback,warped,strength);
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


static constexpr size_t kPasses = 7, kSlots = 128;
static constexpr char const* kPassNames[kPasses] = {
    "capture_copy", "motion_estimation_l0", "synthesis", "present_copy", "present", "downscale_luma", "vector_refine_filter"
};
struct PassQuery {
    ComPtr<ID3D11Query> disjoint, start, end;
    size_t pass = 0;
    uint64_t sequence = 0;
    bool pending = false;
};
struct Samples {
    std::deque<double> v;
    void Add(double x) {
        if (!std::isfinite(x) || x < 0) return;
        v.push_back(x);
        if (v.size() > 512) v.pop_front();
    }
    double Mean() const {
        return v.empty() ? 0.0 : std::accumulate(v.begin(), v.end(), 0.0) / v.size();
    }
    double P95() const {
        if (v.empty()) return 0.0;
        std::vector<double> sorted(v.begin(), v.end());
        size_t index = (size_t)std::ceil(0.95 * sorted.size()) - 1;
        std::nth_element(sorted.begin(), sorted.begin() + index, sorted.end());
        return sorted[index];
    }
    double Jitter() const {
        if (v.empty()) return 0.0;
        double mean = Mean(), square = 0;
        for (double x : v) square += (x - mean) * (x - mean);
        return std::sqrt(square / v.size());
    }
};

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
        ComPtr<IDXGIDevice2> priorityDevice;
        if (SUCCEEDED(m_device.As(&priorityDevice)))
            m_gpuPriorityResult = priorityDevice->SetGPUThreadPriority(m_options.gpuPriority);

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

        InitQueries();
        if (!m_options.csv.empty()) {
            std::error_code ec;
            auto parent = m_options.csv.parent_path();
            if (!parent.empty()) std::filesystem::create_directories(parent, ec);
            std::ofstream reset(m_options.csv, std::ios::trunc);
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
        desc.Flags = DXGI_SWAP_CHAIN_FLAG_FRAME_LATENCY_WAITABLE_OBJECT;
        desc.SwapEffect = DXGI_SWAP_EFFECT_FLIP_DISCARD;
        desc.Scaling = DXGI_SCALING_STRETCH;
        desc.AlphaMode = DXGI_ALPHA_MODE_IGNORE;
        HRESULT hr = factory->CreateSwapChainForHwnd(
            m_device.Get(), m_overlay, &desc, nullptr, nullptr, &m_swapChain);
        if (FAILED(hr)) {
            desc.Flags = 0;
            hr = factory->CreateSwapChainForHwnd(
                m_device.Get(), m_overlay, &desc, nullptr, nullptr, &m_swapChain);
        }
        if (FAILED(hr)) {
            error = L"Could not create output swap chain: " + ErrorText(hr);
            return false;
        }
        ComPtr<IDXGISwapChain2> waitable;
        if (SUCCEEDED(m_swapChain.As(&waitable))) {
            waitable->SetMaximumFrameLatency(1);
            if (desc.Flags & DXGI_SWAP_CHAIN_FLAG_FRAME_LATENCY_WAITABLE_OBJECT)
                m_frameWait = waitable->GetFrameLatencyWaitableObject();
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

        hr = m_device->CreateBuffer(&motion, nullptr, &m_motionFiltered);
        if (FAILED(hr)) return false;
        hr = m_device->CreateShaderResourceView(m_motionFiltered.Get(), &srv, &m_motionFilteredSrv);
        if (FAILED(hr)) return false;
        hr = m_device->CreateUnorderedAccessView(m_motionFiltered.Get(), &uav, &m_motionFilteredUav);
        if (FAILED(hr)) return false;
        D3D11_TEXTURE2D_DESC confidence = input;
        confidence.Width = m_blocksX;
        confidence.Height = m_blocksY;
        confidence.Format = DXGI_FORMAT_R8_UNORM;
        confidence.BindFlags = D3D11_BIND_UNORDERED_ACCESS | D3D11_BIND_SHADER_RESOURCE;
        hr = m_device->CreateTexture2D(&confidence, nullptr, &m_confidence);
        if (FAILED(hr)) return false;
        hr = m_device->CreateUnorderedAccessView(m_confidence.Get(), nullptr, &m_confidenceUav);
        if (FAILED(hr)) return false;

        // Temporal static-pixel persistence, two ping-pong R8 resources.
        D3D11_TEXTURE2D_DESC hudDesc = input;
        hudDesc.Format = DXGI_FORMAT_R8_UNORM;
        hudDesc.BindFlags = D3D11_BIND_SHADER_RESOURCE | D3D11_BIND_UNORDERED_ACCESS;
        for (int i=0;i<2;++i) {
            hr=m_device->CreateTexture2D(&hudDesc,nullptr,&m_hud[i]);
            if (FAILED(hr)) return false;
            hr=m_device->CreateShaderResourceView(m_hud[i].Get(),nullptr,&m_hudSrv[i]);
            if (FAILED(hr)) return false;
            hr=m_device->CreateUnorderedAccessView(m_hud[i].Get(),nullptr,&m_hudUav[i]);
            if (FAILED(hr)) return false;
            const float clear[4]={0,0,0,0};
            m_context->ClearUnorderedAccessViewFloat(m_hudUav[i].Get(),clear);
        }
        // R8_UNORM pyramid. Full-color textures remain exclusive to synthesis.
        D3D11_TEXTURE2D_DESC luma = input;
        luma.Format = DXGI_FORMAT_R8_UNORM;
        luma.BindFlags = D3D11_BIND_UNORDERED_ACCESS | D3D11_BIND_SHADER_RESOURCE;
        for (int i = 0; i < 2; ++i) {
            luma.Width = std::max(1u, (m_width+1)/2);
            luma.Height = std::max(1u, (m_height+1)/2);
            hr = m_device->CreateTexture2D(&luma, nullptr, &m_lumaHalf[i]);
            if (FAILED(hr)) { error = L"Could not allocate R8 half-resolution luma."; return false; }
            hr = m_device->CreateShaderResourceView(m_lumaHalf[i].Get(), nullptr, &m_lumaHalfSrv[i]);
            if (FAILED(hr)) return false;
            hr = m_device->CreateUnorderedAccessView(m_lumaHalf[i].Get(), nullptr, &m_lumaHalfUav[i]);
            if (FAILED(hr)) return false;
            luma.Width = std::max(1u, (m_width+3)/4);
            luma.Height = std::max(1u, (m_height+3)/4);
            hr = m_device->CreateTexture2D(&luma, nullptr, &m_lumaQuarter[i]);
            if (FAILED(hr)) { error = L"Could not allocate R8 quarter-resolution luma."; return false; }
            hr = m_device->CreateShaderResourceView(m_lumaQuarter[i].Get(), nullptr, &m_lumaQuarterSrv[i]);
            if (FAILED(hr)) return false;
            hr = m_device->CreateUnorderedAccessView(m_lumaQuarter[i].Get(), nullptr, &m_lumaQuarterUav[i]);
            if (FAILED(hr)) return false;
        }
        hr = m_device->CreateBuffer(&motion, nullptr, &m_motionPrevious);
        if (FAILED(hr)) return false;
        hr = m_device->CreateShaderResourceView(m_motionPrevious.Get(), &srv, &m_motionPreviousSrv);
        if (FAILED(hr)) return false;
        m_context->ClearUnorderedAccessViewUint(m_motionUav.Get(), std::array<UINT,4>{0,0,0,0}.data());
        m_context->CopyResource(m_motionPrevious.Get(), m_motion.Get());
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
               CompileOne("FilterMotion", m_filterCs, error) &&
               CompileOne("UpdateHud", m_hudCs, error) &&
               CompileOne("LumaDownsample", m_lumaCs, error) &&
               CompileOne("LumaQuarter", m_quarterCs, error) &&
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
            p->dirtyThreshold = m_options.dirtyThreshold;
            p->earlyExitThreshold = m_options.earlyExitThreshold;
            p->occlusionThreshold = m_options.occlusionThreshold;
            p->hudThreshold = m_options.hudThreshold;
            p->debugView = (uint32_t)m_options.debugView;
            p->padding = 0;
            m_context->Unmap(m_params.Get(), 0);
        }
    }

    void Unbind() {
        ID3D11ShaderResourceView* nullSrv[8] = {};
        ID3D11UnorderedAccessView* nullUav[6] = {};
        m_context->CSSetShaderResources(0, 8, nullSrv);
        m_context->CSSetUnorderedAccessViews(0, 6, nullUav, nullptr);
        m_context->CSSetShader(nullptr, nullptr, 0);
    }

    void DispatchLuma(int target) {
        UpdateParams(0.0f);
        ID3D11ShaderResourceView* color = m_currSrv.Get();
        ID3D11UnorderedAccessView* half = m_lumaHalfUav[target].Get();
        m_context->CSSetShader(m_lumaCs.Get(), nullptr, 0);
        m_context->CSSetConstantBuffers(0,1,m_params.GetAddressOf());
        m_context->CSSetShaderResources(1,1,&color);
        m_context->CSSetUnorderedAccessViews(2,1,&half,nullptr);
        m_context->Dispatch(((m_width+1)/2+7)/8,((m_height+1)/2+7)/8,1);
        Unbind();
        ID3D11ShaderResourceView* halfSrv=m_lumaHalfSrv[target].Get();
        ID3D11UnorderedAccessView* quarter=m_lumaQuarterUav[target].Get();
        m_context->CSSetShader(m_quarterCs.Get(),nullptr,0);
        m_context->CSSetShaderResources(4,1,&halfSrv);
        m_context->CSSetUnorderedAccessViews(2,1,&quarter,nullptr);
        m_context->Dispatch(((m_width+3)/4+7)/8,((m_height+3)/4+7)/8,1);
        Unbind();
    }

    void DispatchFlow() {
        UpdateParams(0.0f);
        ID3D11ShaderResourceView* srvs[3] = {
            m_lumaQuarterSrv[1-m_lumaCurrent].Get(),
            m_lumaQuarterSrv[m_lumaCurrent].Get(), m_motionPreviousSrv.Get()
        };
        ID3D11UnorderedAccessView* uavs[1] = {m_motionUav.Get()};
        m_context->CSSetShader(m_flowCs.Get(), nullptr, 0);
        m_context->CSSetConstantBuffers(0, 1, m_params.GetAddressOf());
        m_context->CSSetShaderResources(3, 3, srvs);
        m_context->CSSetUnorderedAccessViews(0, 1, uavs, nullptr);
        m_context->Dispatch((m_blocksX + 7) / 8, (m_blocksY + 7) / 8, 1);
        Unbind();
    }

    void DispatchFilter() {
        ID3D11ShaderResourceView* input=m_motionSrv.Get();
        ID3D11UnorderedAccessView* output[2]={m_motionFilteredUav.Get(),m_confidenceUav.Get()};
        m_context->CSSetShader(m_filterCs.Get(),nullptr,0);
        m_context->CSSetConstantBuffers(0,1,m_params.GetAddressOf());
        m_context->CSSetShaderResources(6,1,&input);
        m_context->CSSetUnorderedAccessViews(3,2,output,nullptr);
        m_context->Dispatch((m_blocksX+7)/8,(m_blocksY+7)/8,1);
        Unbind();
        m_context->CopyResource(m_motionPrevious.Get(),m_motionFiltered.Get());
    }

    void DispatchHud() {
        UpdateParams(0.0f);
        int next=1-m_hudIndex;
        ID3D11ShaderResourceView* inputs[2]={m_prevSrv.Get(),m_currSrv.Get()};
        auto history=m_hudSrv[m_hudIndex].Get();
        auto dest=m_hudUav[next].Get();
        m_context->CSSetShader(m_hudCs.Get(),nullptr,0);
        m_context->CSSetConstantBuffers(0,1,m_params.GetAddressOf());
        m_context->CSSetShaderResources(0,2,inputs);
        m_context->CSSetShaderResources(7,1,&history);
        m_context->CSSetUnorderedAccessViews(5,1,&dest,nullptr);
        m_context->Dispatch((m_width+15)/16,(m_height+15)/16,1);
        Unbind();
        m_hudIndex=next;
    }

    void DispatchFrame(float factor, bool interpolate) {
        UpdateParams(factor);
        ID3D11ShaderResourceView* srvs[3] = {
            m_prevSrv.Get(), m_currSrv.Get(), m_motionFilteredSrv.Get()
        };
        ID3D11UnorderedAccessView* uavs[2] = {nullptr, m_outputUav.Get()};
        m_context->CSSetShader(interpolate ? m_interpCs.Get() : m_copyCs.Get(), nullptr, 0);
        m_context->CSSetConstantBuffers(0, 1, m_params.GetAddressOf());
        m_context->CSSetShaderResources(0, 3, srvs);
        m_context->CSSetUnorderedAccessViews(0, 2, uavs, nullptr);
        auto history=m_hudSrv[m_hudIndex].Get();
        m_context->CSSetShaderResources(7,1,&history);
        m_context->CSSetSamplers(0, 1, m_sampler.GetAddressOf());
        m_context->Dispatch((m_width + 15) / 16, (m_height + 15) / 16, 1);
        Unbind();
    }


    void InitQueries() {
        D3D11_QUERY_DESC d{};
        for (auto& q : m_queries) {
            d.Query = D3D11_QUERY_TIMESTAMP_DISJOINT;
            if (FAILED(m_device->CreateQuery(&d, &q.disjoint))) return;
            d.Query = D3D11_QUERY_TIMESTAMP;
            if (FAILED(m_device->CreateQuery(&d, &q.start))) return;
            if (FAILED(m_device->CreateQuery(&d, &q.end))) return;
        }
        m_queriesReady = true;
    }
    PassQuery* StartPass(size_t pass) {
        if (!m_queriesReady) return nullptr;
        auto& q = m_queries[m_nextQuery];
        if (q.pending) return nullptr;
        m_nextQuery = (m_nextQuery + 1) % kSlots;
        q.pass = pass;
        q.sequence = m_frameSequence;
        m_context->Begin(q.disjoint.Get());
        m_context->End(q.start.Get());
        return &q;
    }
    void StopPass(PassQuery* q) {
        if (!q) return;
        m_context->End(q->end.Get());
        m_context->End(q->disjoint.Get());
        q->pending = true;
    }
    void PollQueries() {
        for (auto& q : m_queries) {
            if (!q.pending || m_frameSequence < q.sequence + 3) continue;
            D3D11_QUERY_DATA_TIMESTAMP_DISJOINT disjoint{};
            UINT64 begin = 0, end = 0;
            UINT flags = D3D11_ASYNC_GETDATA_DONOTFLUSH;
            HRESULT a = m_context->GetData(q.disjoint.Get(), &disjoint, sizeof(disjoint), flags);
            HRESULT b = m_context->GetData(q.start.Get(), &begin, sizeof(begin), flags);
            HRESULT c = m_context->GetData(q.end.Get(), &end, sizeof(end), flags);
            if (a == S_FALSE || b == S_FALSE || c == S_FALSE) continue;
            q.pending = false;
            if (a != S_OK || b != S_OK || c != S_OK ||
                disjoint.Disjoint || !disjoint.Frequency || end < begin) continue;
            m_passStats[q.pass].Add(1000.0 * double(end - begin) / double(disjoint.Frequency));
        }
    }
    double GpuTotal() const {
        double total = 0;
        for (auto const& stats : m_passStats) total += stats.Mean();
        return total;
    }
    void WritePasses(std::ostream& out) {
        out << "\"passes\": {";
        for (size_t i = 0; i < kPasses; ++i) {
            out << "\"" << kPassNames[i] << "\": {\"mean_ms\": ";
            if (m_passStats[i].v.empty()) out << "null, \"p95_ms\": null}";
            else out << m_passStats[i].Mean() << ", \"p95_ms\": " << m_passStats[i].P95() << "}";
            out << ",";
        }
        out << "\"confidence_map\": \"R8_UNORM\"}";
    }
    void WriteCsv(char const* status, double capture, double presented, double generated) {
        if (m_options.csv.empty()) return;
        std::ofstream out(m_options.csv, std::ios::app);
        if (!out) return;
        if (!m_csvHeader) {
            out << "timestamp_unix_ms,status,capture_fps,presented_fps,generated_fps,"
                   "wgc_frame_interval_ms_mean,present_interval_ms_mean,present_pacing_jitter_ms,engine_gpu_ms_mean";
            out << ",adaptive_tier,adaptive_multiplier,adaptive_reason";
            for (auto name : kPassNames) out << "," << name << "_mean_ms," << name << "_p95_ms";
            out << "\n";
            m_csvHeader = true;
        }
        out << std::fixed << std::setprecision(4)
            << duration_cast<milliseconds>(system_clock::now().time_since_epoch()).count()
            << "," << status << "," << capture << "," << presented << "," << generated
            << "," << m_wgcIntervals.Mean() << "," << m_presentIntervals.Mean()
            << "," << m_presentIntervals.Jitter() << "," << GpuTotal()
            << "," << m_tier << "," << m_multiplier << "," << m_reason;
        for (auto const& pass : m_passStats) {
            if (pass.v.empty()) out << ",,";
            else out << "," << pass.Mean() << "," << pass.P95();
        }
        out << "\n";
    }
    void WriteBenchmark(double elapsed, uint64_t captures, uint64_t presents, uint64_t generated) {
        if (m_options.benchmarkOutput.empty()) return;
        std::error_code ec;
        auto parent = m_options.benchmarkOutput.parent_path();
        if (!parent.empty()) std::filesystem::create_directories(parent, ec);
        std::ofstream out(m_options.benchmarkOutput, std::ios::trunc);
        if (!out) return;
        out << std::fixed << std::setprecision(4)
            << "{\"schema_version\":1,\"status\":\"completed\","
            << "\"benchmark_seconds\":" << m_options.benchmarkSeconds << ","
            << "\"target_fps\":" << m_options.targetFps << ","
            << "\"block_size\":" << m_options.blockSize << ","
            << "\"search_radius\":" << m_options.searchRadius << ","
            << "\"capture_fps\":" << captures / std::max(elapsed, 0.001) << ","
            << "\"presented_fps\":" << presents / std::max(elapsed, 0.001) << ","
            << "\"generated_fps\":" << generated / std::max(elapsed, 0.001) << ","
            << "\"wgc_frame_interval_ms_mean\":" << m_wgcIntervals.Mean() << ","
            << "\"present_interval_ms_mean\":" << m_presentIntervals.Mean() << ","
            << "\"present_pacing_jitter_ms\":" << m_presentIntervals.Jitter() << ","
            << "\"engine_gpu_ms_mean\":" << GpuTotal() << ","
            << "\"adaptive_tier\":" << m_tier << ","
            << "\"adaptive_multiplier\":" << m_multiplier << ","
            << "\"adaptive_reason\":\"" << m_reason << "\",";
        WritePasses(out);
        out << "}\n";
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
            if (m_lastWgcTime.time_since_epoch().count())
                m_wgcIntervals.Add(duration<double, std::milli>(now - m_lastWgcTime).count());
            m_lastWgcTime = now;
            auto* copyPass = StartPass(0);
            if (!m_haveCurrent) {
                m_context->CopyResource(m_curr.Get(), texture.get());
                m_context->CopyResource(m_prev.Get(), texture.get());
                m_prevTime = m_currTime = now;
                auto* lumaPass = StartPass(5);
                DispatchLuma(m_lumaCurrent);
                StopPass(lumaPass);
                m_haveCurrent = true;
                m_havePair = false;
            } else {
                std::swap(m_prev, m_curr);
                std::swap(m_prevSrv, m_currSrv);
                m_context->CopyResource(m_curr.Get(), texture.get());
                m_prevTime = m_currTime;
                m_currTime = now;
                StopPass(copyPass);
                copyPass = nullptr;
                m_lumaCurrent = 1-m_lumaCurrent;
                auto* lumaPass = StartPass(5);
                DispatchLuma(m_lumaCurrent);
                StopPass(lumaPass);
                auto* flowPass = StartPass(1);
                DispatchFlow();
                StopPass(flowPass);
                auto* filterPass = StartPass(6);
                DispatchFilter();
                StopPass(filterPass);
                DispatchHud();
                m_havePair = true;
            }
            StopPass(copyPass);
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

    void AdjustController(double captureFps) {
        if (captureFps < 1.0) { m_reason = "awaiting_capture"; m_multiplier = 1; return; }
        if (captureFps < m_options.minBaseFps) {
            m_multiplier = 1;
            m_reason = "base_low";
            return;
        }
        int desired = std::clamp((int)std::ceil(m_options.targetFps / captureFps),1,4);
        const double frameMs = 1000.0 / captureFps;
        const double costMs = GpuTotal();
        const double ratio = costMs / std::max(frameMs,1.0);
        if (ratio > m_options.budgetFraction) {
            ++m_overBudget;
            m_underBudget = 0;
            if (m_overBudget >= 3 && m_tier < 3) { ++m_tier; m_overBudget = 0; }
            m_reason = "gpu_budget_exceeded";
        } else if (ratio < m_options.budgetFraction * 0.65) {
            ++m_underBudget;
            m_overBudget = 0;
            if (m_underBudget >= 8 && m_tier > 0) { --m_tier; m_underBudget = 0; }
            m_reason = m_tier ? "recovering_hysteresis" : "normal";
        } else {
            m_underBudget = 0;
            m_overBudget = 0;
            m_reason = "budget_hysteresis";
        }
        m_multiplier = m_tier >= 3 ? 1 : std::min(desired, m_tier == 2 ? 2 : 4);
    }

    void RenderLoop() {
        using clock = steady_clock;
        const double fps = std::clamp((double)m_options.targetFps, 30.0, 240.0);
        const auto period = duration<double>(1.0 / fps);
        auto next = clock::now();
        auto statsAt = next;
        auto overlayAt = next;
        const auto benchmarkStart = next;
        const uint64_t startCaptures = m_captureCount.load();
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
                    if (m_havePair && m_multiplier > 1) {
                        double dt = duration<double>(m_currTime - m_prevTime).count();
                        dt = std::clamp(dt, 1.0 / 240.0, 0.12);
                        double elapsed = duration<double>(tickStart - m_currTime).count();
                        factor = (float)std::clamp(elapsed / dt, 0.0, 1.0);
                        interpolate = factor > 0.015f && factor < 0.985f;
                        if (m_tier >= 3) interpolate = false;
                    }
                    auto gpuStart = clock::now();
                    auto* synthesis = StartPass(2);
                    DispatchFrame(factor, interpolate);
                    StopPass(synthesis);
                    auto* presentCopy = StartPass(3);
                    m_context->CopyResource(m_swapBuffer.Get(), m_output.Get());
                    StopPass(presentCopy);
                    auto* presentQuery = StartPass(4);
                    HRESULT hr = m_swapChain->Present(1, 0);
                    StopPass(presentQuery);
                    ++m_frameSequence;
                    PollQueries();
                    m_lastEngineMs = (float)(duration<double, std::milli>(
                        clock::now() - gpuStart).count());
                    if (SUCCEEDED(hr)) {
                        auto presentNow = clock::now();
                        if (m_lastPresentTime.time_since_epoch().count())
                            m_presentIntervals.Add(duration<double, std::milli>(presentNow - m_lastPresentTime).count());
                        m_lastPresentTime = presentNow;
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
                std::scoped_lock statsLock(m_gpuMutex);
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
                AdjustController(captureFps);
                WriteCsv("active", captureFps, presentFps, generatedFps);
                WriteTelemetry("active", captureFps, presentFps, generatedFps,
                               latency, m_lastEngineMs.load());
                lastCapture = captures;
                lastPresent = presents;
                lastGenerated = generatedFrames;
                statsAt = now;
            }

            if (m_options.benchmarkSeconds > 0 &&
                now - benchmarkStart >= seconds(m_options.benchmarkSeconds)) break;
            next += duration_cast<clock::duration>(period);
            auto current = clock::now();
            if (next < current - milliseconds(50)) next = current;
            if (m_frameWait) {
                DWORD wait = WaitForSingleObject(m_frameWait, 15);
                if (wait != WAIT_OBJECT_0) std::this_thread::sleep_until(next);
            } else {
                std::this_thread::sleep_until(next);
            }
        }

        m_running = false;
        std::scoped_lock finalStatsLock(m_gpuMutex);
        if (m_options.benchmarkSeconds > 0)
            WriteBenchmark(duration<double>(clock::now() - benchmarkStart).count(),
                           m_captureCount.load() - startCaptures,
                           m_presentCount.load(), m_generatedCount.load());
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
            << "  \"engine_gpu_ms_mean\": " << GpuTotal() << ",\n"
            << "  \"adaptive_tier\": " << m_tier << ",\n"
            << "  \"adaptive_multiplier\": " << m_multiplier << ",\n"
            << "  \"adaptive_reason\": \"" << m_reason << "\",\n"
            << "  \"gpu_thread_priority_hresult\": " << (long)m_gpuPriorityResult << ",\n"
            << "  \"waitable_swap_chain\": " << (m_frameWait ? "true" : "false") << ",\n"
            << "  \"wgc_frame_interval_ms_mean\": " << m_wgcIntervals.Mean() << ",\n"
            << "  \"present_interval_ms_mean\": " << m_presentIntervals.Mean() << ",\n"
            << "  \"present_pacing_jitter_ms\": " << m_presentIntervals.Jitter() << ",\n"
            << "  \"width\": " << m_width << ",\n"
            << "  \"height\": " << m_height << ",\n"
            << "  \"block_size\": " << m_options.blockSize << ",\n"
            << "  \"search_radius\": " << m_options.searchRadius << ",\n"
            << "  "; 
        WritePasses(out);
        out << "\n"
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
    ComPtr<ID3D11ComputeShader> m_lumaCs, m_quarterCs, m_filterCs, m_hudCs;
    ComPtr<ID3D11Texture2D> m_hud[2];
    ComPtr<ID3D11ShaderResourceView> m_hudSrv[2];
    ComPtr<ID3D11UnorderedAccessView> m_hudUav[2];
    int m_hudIndex = 0;
    ComPtr<ID3D11Buffer> m_motionFiltered;
    ComPtr<ID3D11ShaderResourceView> m_motionFilteredSrv;
    ComPtr<ID3D11UnorderedAccessView> m_motionFilteredUav;
    ComPtr<ID3D11Texture2D> m_confidence;
    ComPtr<ID3D11UnorderedAccessView> m_confidenceUav;
    ComPtr<ID3D11Texture2D> m_lumaHalf[2], m_lumaQuarter[2];
    ComPtr<ID3D11ShaderResourceView> m_lumaHalfSrv[2], m_lumaQuarterSrv[2];
    ComPtr<ID3D11UnorderedAccessView> m_lumaHalfUav[2], m_lumaQuarterUav[2];
    ComPtr<ID3D11Buffer> m_motionPrevious;
    ComPtr<ID3D11ShaderResourceView> m_motionPreviousSrv;

    std::array<PassQuery, kSlots> m_queries{};
    std::array<Samples, kPasses> m_passStats{};
    Samples m_wgcIntervals, m_presentIntervals;
    steady_clock::time_point m_lastWgcTime{}, m_lastPresentTime{};
    size_t m_nextQuery = 0;
    uint64_t m_frameSequence = 0;
    bool m_queriesReady = false, m_csvHeader = false;
    HANDLE m_frameWait = nullptr; // Owned by the DXGI swapchain, do not CloseHandle.
    HRESULT m_gpuPriorityResult = E_NOTIMPL;
    int m_tier = 0, m_multiplier = 1, m_overBudget = 0, m_underBudget = 0;
    const char* m_reason = "starting";
    std::mutex m_gpuMutex;
    std::thread m_renderThread;
    std::atomic<bool> m_running{false};
    std::atomic<bool> m_resizeDetected{false};
    bool m_haveCurrent = false;
    bool m_havePair = false;
    int m_lumaCurrent = 0;
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
        } else if (arg == L"--csv") {
            if (auto v = next()) out.csv = v;
        } else if (arg == L"--benchmark") {
            if (auto v = next()) out.benchmarkSeconds = _wtoi(v);
        } else if (arg == L"--benchmark-output") {
            if (auto v = next()) out.benchmarkOutput = v;
        } else if (arg == L"--dirty-threshold") {
            if (auto v = next()) out.dirtyThreshold = (float)_wtof(v);
        } else if (arg == L"--early-exit-threshold") {
            if (auto v = next()) out.earlyExitThreshold = (float)_wtof(v);
        } else if (arg == L"--debug-view") {
            if (auto v = next()) {
                std::wstring mode=v;
                out.debugView = mode==L"confidence"?1:(mode==L"vectors"?2:0);
            }
        } else if (arg == L"--occlusion-threshold") {
            if (auto v = next()) out.occlusionThreshold=(float)_wtof(v);
        } else if (arg == L"--hud-threshold") {
            if (auto v = next()) out.hudThreshold=(float)_wtof(v);
        } else if (arg == L"--min-base-fps") {
            if (auto v=next()) out.minBaseFps=_wtof(v);
        } else if (arg == L"--budget-fraction") {
            if (auto v=next()) out.budgetFraction=_wtof(v);
        } else if (arg == L"--gpu-priority") {
            if (auto v=next()) out.gpuPriority=_wtoi(v);
        } else if (arg == L"--telemetry") {
            if (auto v = next()) out.telemetry = v;
        }
    }
    out.targetFps = std::clamp(out.targetFps, 30, 240);
    out.minBaseFps = std::clamp(out.minBaseFps, 5.0, 60.0);
    out.budgetFraction = std::clamp(out.budgetFraction, 0.05, 0.75);
    out.gpuPriority = std::clamp(out.gpuPriority,-7,0);
    out.dirtyThreshold = std::clamp(out.dirtyThreshold, 0.001f, 0.5f);
    out.earlyExitThreshold = std::clamp(out.earlyExitThreshold, 0.001f, 0.5f);
    out.occlusionThreshold = std::clamp(out.occlusionThreshold, 0.01f, 1.0f);
    out.hudThreshold = std::clamp(out.hudThreshold, 0.001f, 0.5f);
    out.blockSize = std::clamp(out.blockSize, 8, 64);
    // Keep an even radius because the lightweight search advances by 2 pixels.
    out.searchRadius = std::clamp(out.searchRadius, 2, 24);
    if (out.searchRadius & 1) ++out.searchRadius;
    if (out.benchmarkSeconds < 0 || out.benchmarkSeconds > 86400) return false;
    if (out.benchmarkSeconds && out.benchmarkOutput.empty()) return false;
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
