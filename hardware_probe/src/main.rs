use amd_adlx::*;

fn opt_number(value: Option<f64>) -> String {
    value.map(|v| format!("{v:.3}")).unwrap_or_else(|| "null".into())
}

fn opt_integer(value: Option<i32>) -> String {
    value.map(|v| v.to_string()).unwrap_or_else(|| "null".into())
}

fn main() {
    let helper = match AdlxHelper::new() {
        Ok(value) => value,
        Err(_) => {
            println!("{}", r#"{"error":"ADLX initialization failed"}"#);
            return;
        }
    };

    unsafe {
        let sys = helper.system_services();
        let sys_vtbl = &*(*sys).pVtbl;
        let mut perf: *mut IADLXPerformanceMonitoringServices = std::ptr::null_mut();
        if !adlx_succeeded((sys_vtbl.GetPerformanceMonitoringServices)(sys, &mut perf)) {
            println!("{}", r#"{"error":"performance monitoring unavailable"}"#);
            return;
        }
        let perf_vtbl = &*(*perf).pVtbl;
        let mut gpus: *mut IADLXGPUList = std::ptr::null_mut();
        if !adlx_succeeded((sys_vtbl.GetGPUs)(sys, &mut gpus)) {
            println!("{}", r#"{"error":"GPU list unavailable"}"#);
            (perf_vtbl.Release)(perf);
            return;
        }
        let list_vtbl = &*(*gpus).pVtbl;
        let mut gpu: *mut IADLXGPU = std::ptr::null_mut();
        if !adlx_succeeded((list_vtbl.At_GPUList)(gpus, (list_vtbl.Begin)(gpus), &mut gpu)) {
            println!("{}", r#"{"error":"AMD GPU unavailable"}"#);
            (list_vtbl.Release)(gpus);
            (perf_vtbl.Release)(perf);
            return;
        }

        let mut support: *mut IADLXGPUMetricsSupport = std::ptr::null_mut();
        let mut metrics: *mut IADLXGPUMetrics = std::ptr::null_mut();
        if !adlx_succeeded((perf_vtbl.GetSupportedGPUMetrics)(perf, gpu, &mut support))
            || !adlx_succeeded((perf_vtbl.GetCurrentGPUMetrics)(perf, gpu, &mut metrics))
        {
            println!("{}", r#"{"error":"GPU metrics unavailable"}"#);
        } else {
            let s = &*(*support).pVtbl;
            let m = &*(*metrics).pVtbl;
            let mut supported: adlx_bool = 0;
            macro_rules! metric_f64 {
                ($check:ident, $get:ident) => {{
                    if adlx_succeeded((s.$check)(support, &mut supported)) && supported != 0 {
                        let mut value: adlx_double = 0.0;
                        if adlx_succeeded((m.$get)(metrics, &mut value)) { Some(value) } else { None }
                    } else { None }
                }};
            }
            macro_rules! metric_i32 {
                ($check:ident, $get:ident) => {{
                    if adlx_succeeded((s.$check)(support, &mut supported)) && supported != 0 {
                        let mut value: adlx_int = 0;
                        if adlx_succeeded((m.$get)(metrics, &mut value)) { Some(value) } else { None }
                    } else { None }
                }};
            }
            let usage = metric_f64!(IsSupportedGPUUsage, GPUUsage);
            let temperature = metric_f64!(IsSupportedGPUTemperature, GPUTemperature);
            let hotspot = metric_f64!(IsSupportedGPUHotspotTemperature, GPUHotspotTemperature);
            let power = metric_f64!(IsSupportedGPUPower, GPUPower);
            let board_power = metric_f64!(IsSupportedGPUTotalBoardPower, GPUTotalBoardPower);
            let fan = metric_i32!(IsSupportedGPUFanSpeed, GPUFanSpeed);
            let vram = metric_i32!(IsSupportedGPUVRAM, GPUVRAM);
            println!(
                "{{\"gpu_usage_pct\":{},\"gpu_temp_c\":{},\"gpu_hotspot_c\":{},\"gpu_power_w\":{},\"gpu_board_power_w\":{},\"gpu_fan_rpm\":{},\"gpu_vram_mb\":{}}}",
                opt_number(usage), opt_number(temperature), opt_number(hotspot), opt_number(power),
                opt_number(board_power), opt_integer(fan), opt_integer(vram)
            );
            ((&*(*metrics).pVtbl).Release)(metrics);
            ((&*(*support).pVtbl).Release)(support);
        }
        ((&*(*gpu).pVtbl).Release)(gpu);
        (list_vtbl.Release)(gpus);
        (perf_vtbl.Release)(perf);
    }
}
