// Photo-Aiid-system · Tauri 外壳
//
// 启动流程：
//   1. setup() 中拉起冻结好的 Python 后端（PyInstaller onedir，作为打包资源）。
//   2. 后台线程用 TCP 探测 127.0.0.1:8000，端口就绪后创建主窗口。
//   3. 窗口直接加载 http://127.0.0.1:8000 —— 后端同源托管前端，/api 原样可用。
//   4. 退出时杀掉后端子进程。

use std::net::{SocketAddr, TcpStream};
use std::process::{Child, Command};
use std::sync::Mutex;
use std::time::Duration;

use tauri::{Manager, WebviewUrl, WebviewWindowBuilder};

const HOST: &str = "127.0.0.1";
const PORT: u16 = 8000;

// 持有后端子进程句柄，退出时统一清理。
struct BackendProcess(Mutex<Option<Child>>);

/// 解析后端可执行文件路径：优先用打包资源，开发期回退到本地 freeze 产物。
fn backend_executable(app: &tauri::App) -> Option<std::path::PathBuf> {
    // 打包后：<Resources>/resources/backend/photo-aiid-backend
    if let Ok(res_dir) = app.path().resource_dir() {
        let bundled = res_dir
            .join("resources")
            .join("backend")
            .join("photo-aiid-backend");
        if bundled.exists() {
            return Some(bundled);
        }
    }
    // 开发期回退：仓库内 PyInstaller 产物
    let dev = std::env::current_dir()
        .ok()?
        .join("../backend/dist/photo-aiid-backend/photo-aiid-backend");
    if dev.exists() {
        return Some(dev);
    }
    None
}

fn spawn_backend(app: &tauri::App) -> Option<Child> {
    let exe = backend_executable(app)?;
    log::info!("启动后端: {:?}", exe);
    Command::new(&exe)
        .env("PHOTO_AIID_HOST", HOST)
        .env("PHOTO_AIID_PORT", PORT.to_string())
        .spawn()
        .map_err(|e| log::error!("后端启动失败: {e}"))
        .ok()
}

/// 阻塞等待端口就绪，最多约 30 秒。
fn wait_for_backend() -> bool {
    let addr: SocketAddr = format!("{HOST}:{PORT}").parse().unwrap();
    for _ in 0..150 {
        if TcpStream::connect_timeout(&addr, Duration::from_millis(200)).is_ok() {
            return true;
        }
        std::thread::sleep(Duration::from_millis(200));
    }
    false
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_log::Builder::default().build())
        .setup(|app| {
            let child = spawn_backend(app);
            app.manage(BackendProcess(Mutex::new(child)));

            let handle = app.handle().clone();
            std::thread::spawn(move || {
                if !wait_for_backend() {
                    log::error!("后端在超时内未就绪");
                }
                let url = format!("http://{HOST}:{PORT}");
                let res = WebviewWindowBuilder::new(
                    &handle,
                    "main",
                    WebviewUrl::External(url.parse().unwrap()),
                )
                .title("Photo-Aiid-system")
                .inner_size(1280.0, 820.0)
                .min_inner_size(960.0, 640.0)
                .resizable(true)
                .build();
                if let Err(e) = res {
                    log::error!("创建窗口失败: {e}");
                }
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while running tauri application")
        .run(|app_handle, event| match event {
            // 关闭任一窗口即退出整个 app（macOS 默认会保活，这里强制退出）
            tauri::RunEvent::WindowEvent {
                event: tauri::WindowEvent::CloseRequested { .. },
                ..
            } => {
                app_handle.exit(0);
            }
            // 退出时杀掉后端子进程
            tauri::RunEvent::Exit => {
                if let Some(state) = app_handle.try_state::<BackendProcess>() {
                    if let Ok(mut guard) = state.0.lock() {
                        if let Some(mut child) = guard.take() {
                            let _ = child.kill();
                        }
                    }
                }
            }
            _ => {}
        });
}
