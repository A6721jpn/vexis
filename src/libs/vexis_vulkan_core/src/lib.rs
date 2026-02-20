use pyo3::prelude::*;

pub mod parser;
pub mod renderer;

/// This is the main python module initialization.
#[pymodule]
fn vexis_vulkan_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<parser::XpltFastParser>()?;
    m.add_class::<renderer::VulkanRenderer>()?;
    Ok(())
}
