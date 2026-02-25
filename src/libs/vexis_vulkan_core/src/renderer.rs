use pyo3::prelude::*;
use pyo3::exceptions::PyRuntimeError;
use vulkano::instance::{Instance, InstanceCreateInfo, InstanceExtensions};
use vulkano::device::{Device, DeviceCreateInfo, QueueCreateInfo, DeviceExtensions, Queue};
use vulkano::memory::allocator::{StandardMemoryAllocator, AllocationCreateInfo, MemoryTypeFilter};
use vulkano::VulkanLibrary;
use vulkano::format::Format;
use vulkano::image::{Image, ImageCreateInfo, ImageType, ImageUsage, view::ImageView};
use vulkano::buffer::{Buffer, BufferCreateInfo, BufferUsage};
use vulkano::render_pass::{RenderPass, Framebuffer, FramebufferCreateInfo, Subpass};
use vulkano::command_buffer::allocator::StandardCommandBufferAllocator;
use vulkano::command_buffer::{AutoCommandBufferBuilder, CommandBufferUsage, RenderPassBeginInfo, SubpassBeginInfo, SubpassContents};
use vulkano::sync::{self, GpuFuture};

use vulkano::pipeline::graphics::GraphicsPipelineCreateInfo;
use vulkano::pipeline::graphics::color_blend::{ColorBlendAttachmentState, ColorBlendState};
use vulkano::pipeline::graphics::input_assembly::InputAssemblyState;
use vulkano::pipeline::graphics::multisample::MultisampleState;
use vulkano::pipeline::graphics::rasterization::RasterizationState;
use vulkano::pipeline::graphics::viewport::{Viewport, ViewportState};
use vulkano::pipeline::graphics::depth_stencil::{DepthState, DepthStencilState};
use vulkano::pipeline::{GraphicsPipeline, Pipeline, PipelineShaderStageCreateInfo, layout::PipelineLayoutCreateInfo};
use vulkano::shader::ShaderModule;
use vulkano::pipeline::graphics::vertex_input::{
    Vertex as VulkanoVertex, VertexInputState, VertexInputBindingDescription,
    VertexInputRate, VertexInputAttributeDescription
};
use vulkano::pipeline::layout::PushConstantRange;
use vulkano::shader::ShaderStages;
use vulkano::buffer::Subbuffer;

use std::sync::Arc;
use bytemuck::{Pod, Zeroable};

#[repr(C)]
#[derive(Clone, Copy, Debug, Default, Pod, Zeroable)]
pub struct PushConstants {
    pub mvp: [[f32; 4]; 4],
    pub min_val: f32,
    pub max_val: f32,
}

#[derive(VulkanoVertex, Clone, Copy, Debug, Default, Pod, Zeroable)]
#[repr(C)]
pub struct PositionVertex {
    #[format(R32G32B32_SFLOAT)]
    pub position: [f32; 3],
}

#[derive(VulkanoVertex, Clone, Copy, Debug, Default, Pod, Zeroable)]
#[repr(C)]
pub struct ScalarVertex {
    #[format(R32_SFLOAT)]
    pub scalar: f32,
}

fn compile_shader(src: &str, stage: naga::ShaderStage, _entry_point: &str) -> Result<Vec<u32>, String> {
    let mut frontend = naga::front::glsl::Frontend::default();
    let options = naga::front::glsl::Options {
        stage,
        defines: naga::FastHashMap::default(),
    };
    let module = frontend.parse(&options, src).map_err(|e| format!("GLSL parse error: {:?}", e))?;
    let mut validator = naga::valid::Validator::new(naga::valid::ValidationFlags::all(), naga::valid::Capabilities::all());
    let info = validator.validate(&module).map_err(|e| format!("Validation error: {:?}", e))?;
    let spv_options = naga::back::spv::Options {
        flags: naga::back::spv::WriterFlags::DEBUG,
        ..Default::default()
    };
    let mut writer = naga::back::spv::Writer::new(&spv_options).map_err(|e| format!("SPV writer error: {:?}", e))?;
    let mut spv = Vec::new();
    writer.write(&module, &info, None, &None, &mut spv).map_err(|e| format!("SPV write error: {:?}", e))?;
    Ok(spv)
}

#[pyclass]
pub struct VulkanRenderer {
    width: u32,
    height: u32,
    instance: Arc<Instance>,
    device: Arc<Device>,
    queue: Arc<Queue>,
    allocator: Arc<StandardMemoryAllocator>,
    command_buffer_allocator: StandardCommandBufferAllocator,
    render_pass: Arc<RenderPass>,
    pipeline: Arc<GraphicsPipeline>,
    
    // Cached resources
    color_image: Option<Arc<Image>>,
    depth_image: Option<Arc<Image>>,
    framebuffer: Option<Arc<Framebuffer>>,
    positions_buffer: Option<Subbuffer<[crate::renderer::PositionVertex]>>,
    indices_buffer: Option<Subbuffer<[u32]>>,
    num_indices: u32,
}

#[pymethods]
impl VulkanRenderer {
    #[new]
    pub fn new(width: u32, height: u32) -> PyResult<Self> {
        let library = VulkanLibrary::new()
            .map_err(|e| PyErr::new::<PyRuntimeError, _>(format!("Failed to load Vulkan library: {}", e)))?;
        
        let instance = Instance::new(library, InstanceCreateInfo {
            enabled_extensions: InstanceExtensions::empty(), 
            ..Default::default()
        }).map_err(|e| PyErr::new::<PyRuntimeError, _>(format!("Failed to create Vulkan instance: {}", e)))?;

        let device_extensions = DeviceExtensions {
            khr_storage_buffer_storage_class: true,
            ..DeviceExtensions::empty()
        };

        let physical_device = instance.enumerate_physical_devices()
            .map_err(|e| PyErr::new::<PyRuntimeError, _>(format!("Failed to enumerate physical devices: {}", e)))?
            .next()
            .ok_or_else(|| PyErr::new::<PyRuntimeError, _>("No physical devices found"))?;

        let queue_family_index = physical_device.queue_family_properties()
            .iter()
            .enumerate()
            .position(|(_, q)| q.queue_flags.intersects(vulkano::device::QueueFlags::GRAPHICS))
            .ok_or_else(|| PyErr::new::<PyRuntimeError, _>("No graphics queue family found"))? as u32;

        let (device, mut queues) = Device::new(
            physical_device,
            DeviceCreateInfo {
                queue_create_infos: vec![QueueCreateInfo {
                    queue_family_index,
                    ..Default::default()
                }],
                enabled_extensions: device_extensions,
                ..Default::default()
            },
        ).map_err(|e| PyErr::new::<PyRuntimeError, _>(format!("Failed to create device: {}", e)))?;

        let queue = queues.next().ok_or_else(|| PyErr::new::<PyRuntimeError, _>("Failed to get queue"))?;
        let allocator = Arc::new(StandardMemoryAllocator::new_default(device.clone()));
        let command_buffer_allocator = StandardCommandBufferAllocator::new(device.clone(), Default::default());

        let render_pass = vulkano::single_pass_renderpass!(
            device.clone(),
            attachments: {
                color: {
                    format: Format::R8G8B8A8_UNORM,
                    samples: 1,
                    load_op: Clear,
                    store_op: Store,
                },
                depth: {
                    format: Format::D16_UNORM,
                    samples: 1,
                    load_op: Clear,
                    store_op: DontCare,
                }
            },
            pass: {
                color: [color],
                depth_stencil: {depth}
            }
        ).map_err(|e| PyErr::new::<PyRuntimeError, _>(format!("Failed to create render pass: {}", e)))?;

        // Compile shaders
        let vs_src = r"
            #version 450
            layout(push_constant) uniform PushConstants {
                mat4 mvp;
                float min_val;
                float max_val;
            } pc;
            layout(location = 0) in vec3 position;
            layout(location = 1) in float scalar;
            layout(location = 0) out float v_scalar;
            void main() {
                gl_Position = pc.mvp * vec4(position, 1.0);
                v_scalar = scalar;
            }
        ";
        let fs_src = r"
            #version 450
            layout(push_constant) uniform PushConstants {
                mat4 mvp;
                float min_val;
                float max_val;
            } pc;
            layout(location = 0) in float v_scalar;
            layout(location = 0) out vec4 f_color;
            void main() {
                float t = 0.0;
                if (pc.max_val > pc.min_val) {
                    t = (v_scalar - pc.min_val) / (pc.max_val - pc.min_val);
                }
                t = clamp(t, 0.0, 1.0);
                float r = clamp(1.5 - abs(4.0 * t - 3.0), 0.0, 1.0);
                float g = clamp(1.5 - abs(4.0 * t - 2.0), 0.0, 1.0);
                float b = clamp(1.5 - abs(4.0 * t - 1.0), 0.0, 1.0);
                f_color = vec4(r, g, b, 1.0);
            }
        ";

        let vs_spv = compile_shader(vs_src, naga::ShaderStage::Vertex, "main").map_err(|e| PyErr::new::<PyRuntimeError, _>(e))?;
        let fs_spv = compile_shader(fs_src, naga::ShaderStage::Fragment, "main").map_err(|e| PyErr::new::<PyRuntimeError, _>(e))?;

        let vs_module = unsafe { ShaderModule::new(device.clone(), vulkano::shader::ShaderModuleCreateInfo::new(&vs_spv)) }.map_err(|e| PyErr::new::<PyRuntimeError, _>(format!("VS creation error: {:?}", e)))?;
        let fs_module = unsafe { ShaderModule::new(device.clone(), vulkano::shader::ShaderModuleCreateInfo::new(&fs_spv)) }.map_err(|e| PyErr::new::<PyRuntimeError, _>(format!("FS creation error: {:?}", e)))?;

        let vs_entry = vs_module.entry_point("main").ok_or_else(|| PyErr::new::<PyRuntimeError, _>("Failed to find VS entry point"))?;
        let fs_entry = fs_module.entry_point("main").ok_or_else(|| PyErr::new::<PyRuntimeError, _>("Failed to find FS entry point"))?;

        let pipeline_layout = vulkano::pipeline::layout::PipelineLayout::new(
            device.clone(),
            PipelineLayoutCreateInfo {
                push_constant_ranges: vec![PushConstantRange {
                    stages: ShaderStages::VERTEX | ShaderStages::FRAGMENT,
                    offset: 0,
                    size: std::mem::size_of::<PushConstants>() as u32,
                }],
                ..Default::default()
            }
        ).map_err(|e| PyErr::new::<PyRuntimeError, _>(format!("Failed to create pipeline layout: {}", e)))?;

        let subpass = Subpass::from(render_pass.clone(), 0)
            .ok_or_else(|| PyErr::new::<PyRuntimeError, _>("Failed to get subpass"))?;

        let pipeline = GraphicsPipeline::new(
            device.clone(),
            None,
            GraphicsPipelineCreateInfo {
                stages: vec![
                    PipelineShaderStageCreateInfo::new(vs_entry.clone()),
                    PipelineShaderStageCreateInfo::new(fs_entry),
                ].into(),
                vertex_input_state: Some(
                    VertexInputState::new()
                        .binding(
                            0,
                            VertexInputBindingDescription {
                                stride: std::mem::size_of::<crate::renderer::PositionVertex>() as u32,
                                input_rate: VertexInputRate::Vertex,
                            },
                        )
                        .binding(
                            1,
                            VertexInputBindingDescription {
                                stride: std::mem::size_of::<crate::renderer::ScalarVertex>() as u32,
                                input_rate: VertexInputRate::Vertex,
                            },
                        )
                        .attribute(
                            0,
                            VertexInputAttributeDescription {
                                binding: 0,
                                format: Format::R32G32B32_SFLOAT,
                                offset: 0,
                            },
                        )
                        .attribute(
                            1,
                            VertexInputAttributeDescription {
                                binding: 1,
                                format: Format::R32_SFLOAT,
                                offset: 0,
                            },
                        )
                ),
                input_assembly_state: Some(InputAssemblyState::default()),
                viewport_state: Some(ViewportState {
                    viewports: vec![Viewport {
                        offset: [0.0, 0.0],
                        extent: [width as f32, height as f32],
                        depth_range: 0.0..=1.0,
                    }].into(),
                    ..Default::default()
                }),
                rasterization_state: Some(RasterizationState::default()),
                multisample_state: Some(MultisampleState::default()),
                depth_stencil_state: Some(DepthStencilState {
                    depth: Some(DepthState::simple()),
                    ..Default::default()
                }),
                color_blend_state: Some(ColorBlendState::with_attachment_states(
                    1, // Known to be 1 color attachment
                    ColorBlendAttachmentState::default(),
                )),
                subpass: Some(subpass.into()),
                ..GraphicsPipelineCreateInfo::layout(pipeline_layout)
            },
        ).map_err(|e| PyErr::new::<PyRuntimeError, _>(format!("Failed to create pipeline: {}", e)))?;

        let mut renderer = VulkanRenderer { 
            width, 
            height, 
            instance, 
            device, 
            queue, 
            allocator,
            command_buffer_allocator,
            render_pass,
            pipeline,
            color_image: None,
            depth_image: None,
            framebuffer: None,
            positions_buffer: None,
            indices_buffer: None,
            num_indices: 0,
        };
        
        let _ = renderer.resize(width, height);
        
        Ok(renderer)
    }

    pub fn resize(&mut self, width: u32, height: u32) -> PyResult<()> {
        self.width = width;
        self.height = height;
        
        if width == 0 || height == 0 {
            return Ok(());
        }

        let image = Image::new(
            self.allocator.clone(),
            ImageCreateInfo {
                image_type: ImageType::Dim2d,
                format: Format::R8G8B8A8_UNORM,
                extent: [self.width, self.height, 1],
                usage: ImageUsage::COLOR_ATTACHMENT | ImageUsage::TRANSFER_SRC,
                ..Default::default()
            },
            AllocationCreateInfo {
                memory_type_filter: MemoryTypeFilter::PREFER_DEVICE,
                ..Default::default()
            },
        ).map_err(|e| PyErr::new::<PyRuntimeError, _>(format!("Failed to create image: {}", e)))?;

        let view = ImageView::new_default(image.clone())
            .map_err(|e| PyErr::new::<PyRuntimeError, _>(format!("Failed to create image view: {}", e)))?;

        let depth_buffer = Image::new(
            self.allocator.clone(),
            ImageCreateInfo {
                image_type: ImageType::Dim2d,
                format: Format::D16_UNORM,
                extent: [self.width, self.height, 1],
                usage: ImageUsage::DEPTH_STENCIL_ATTACHMENT,
                ..Default::default()
            },
            AllocationCreateInfo {
                memory_type_filter: MemoryTypeFilter::PREFER_DEVICE,
                ..Default::default()
            },
        ).map_err(|e| PyErr::new::<PyRuntimeError, _>(format!("Failed to create depth buffer: {}", e)))?;

        let depth_view = ImageView::new_default(depth_buffer.clone())
            .map_err(|e| PyErr::new::<PyRuntimeError, _>(format!("Failed to create depth buffer view: {}", e)))?;

        let framebuffer = Framebuffer::new(
            self.render_pass.clone(),
            FramebufferCreateInfo {
                attachments: vec![view, depth_view],
                ..Default::default()
            },
        ).map_err(|e| PyErr::new::<PyRuntimeError, _>(format!("Failed to create framebuffer: {}", e)))?;

        self.color_image = Some(image);
        self.depth_image = Some(depth_buffer);
        self.framebuffer = Some(framebuffer);

        Ok(())
    }

    #[pyo3(signature = (positions, indices))]
    pub fn set_mesh(&mut self, positions: Vec<f32>, indices: Vec<u32>) -> PyResult<()> {
        if positions.is_empty() || indices.is_empty() {
            self.positions_buffer = None;
            self.indices_buffer = None;
            self.num_indices = 0;
            return Ok(());
        }

        let num_vertices = positions.len() / 3;
        let mut vertices = Vec::with_capacity(num_vertices);
        for i in 0..num_vertices {
            vertices.push(crate::renderer::PositionVertex {
                position: [positions[i * 3], positions[i * 3 + 1], positions[i * 3 + 2]],
            });
        }

        let vertex_buffer = Buffer::from_iter(
            self.allocator.clone(),
            BufferCreateInfo {
                usage: BufferUsage::VERTEX_BUFFER,
                ..Default::default()
            },
            AllocationCreateInfo {
                memory_type_filter: MemoryTypeFilter::PREFER_HOST | MemoryTypeFilter::HOST_SEQUENTIAL_WRITE,
                ..Default::default()
            },
            vertices,
        ).map_err(|e| PyErr::new::<PyRuntimeError, _>(format!("Failed to create vertex buffer: {}", e)))?;

        let index_buffer = Buffer::from_iter(
            self.allocator.clone(),
            BufferCreateInfo {
                usage: BufferUsage::INDEX_BUFFER,
                ..Default::default()
            },
            AllocationCreateInfo {
                memory_type_filter: MemoryTypeFilter::PREFER_HOST | MemoryTypeFilter::HOST_SEQUENTIAL_WRITE,
                ..Default::default()
            },
            indices.clone(),
        ).map_err(|e| PyErr::new::<PyRuntimeError, _>(format!("Failed to create index buffer: {}", e)))?;

        self.positions_buffer = Some(vertex_buffer);
        self.indices_buffer = Some(index_buffer);
        self.num_indices = indices.len() as u32;

        Ok(())
    }

    #[pyo3(signature = (values, mvp_matrix, min_val, max_val))]
    pub fn render_mesh(
        &mut self,
        values: Vec<f32>,
        mvp_matrix: [[f32; 4]; 4],
        min_val: f32,
        max_val: f32,
    ) -> PyResult<Vec<u8>> {
        if self.framebuffer.is_none() || self.positions_buffer.is_none() || self.indices_buffer.is_none() || self.color_image.is_none() {
            return Ok(vec![0; (self.width * self.height * 4) as usize]);
        }
        if values.is_empty() {
            return Ok(vec![0; (self.width * self.height * 4) as usize]);
        }

        let num_vertices = values.len();
        let mut scalar_vertices = Vec::with_capacity(num_vertices);
        for i in 0..num_vertices {
            scalar_vertices.push(crate::renderer::ScalarVertex {
                scalar: values[i],
            });
        }

        let scalar_buffer = Buffer::from_iter(
            self.allocator.clone(),
            BufferCreateInfo {
                usage: BufferUsage::VERTEX_BUFFER,
                ..Default::default()
            },
            AllocationCreateInfo {
                memory_type_filter: MemoryTypeFilter::PREFER_HOST | MemoryTypeFilter::HOST_SEQUENTIAL_WRITE,
                ..Default::default()
            },
            scalar_vertices,
        ).map_err(|e| PyErr::new::<PyRuntimeError, _>(format!("Failed to create scalar buffer: {}", e)))?;

        let buf = Buffer::from_iter(
            self.allocator.clone(),
            BufferCreateInfo {
                usage: BufferUsage::TRANSFER_DST,
                ..Default::default()
            },
            AllocationCreateInfo {
                memory_type_filter: MemoryTypeFilter::PREFER_HOST | MemoryTypeFilter::HOST_RANDOM_ACCESS,
                ..Default::default()
            },
            (0..self.width * self.height * 4).map(|_| 0u8),
        ).map_err(|e| PyErr::new::<PyRuntimeError, _>(format!("Failed to create transfer buffer: {}", e)))?;

        let mut builder = AutoCommandBufferBuilder::primary(
            &self.command_buffer_allocator,
            self.queue.queue_family_index(),
            CommandBufferUsage::OneTimeSubmit,
        ).map_err(|e| PyErr::new::<PyRuntimeError, _>(format!("Failed to create command buffer builder: {}", e)))?;

        let push_constants = PushConstants {
            mvp: mvp_matrix,
            min_val,
            max_val,
        };

        let pos_buf = self.positions_buffer.as_ref().unwrap().clone();
        let idx_buf = self.indices_buffer.as_ref().unwrap().clone();
        let fb = self.framebuffer.as_ref().unwrap().clone();
        let img = self.color_image.as_ref().unwrap().clone();

        builder
            .begin_render_pass(
                RenderPassBeginInfo {
                    clear_values: vec![Some([0.059, 0.059, 0.102, 1.0].into()), Some(1f32.into())],
                    ..RenderPassBeginInfo::framebuffer(fb)
                },
                SubpassBeginInfo {
                    contents: SubpassContents::Inline,
                    ..Default::default()
                },
            )
            .map_err(|e| PyErr::new::<PyRuntimeError, _>(format!("Failed to begin render pass: {}", e)))?
            .bind_pipeline_graphics(self.pipeline.clone())
            .unwrap()
            .push_constants(self.pipeline.layout().clone(), 0, push_constants)
            .unwrap()
            .bind_vertex_buffers(0, pos_buf)
            .unwrap()
            .bind_vertex_buffers(1, scalar_buffer)
            .unwrap()
            .bind_index_buffer(idx_buf)
            .unwrap()
            .draw_indexed(self.num_indices, 1, 0, 0, 0)
            .unwrap();
        
        builder
            .end_render_pass(Default::default())
            .map_err(|e| PyErr::new::<PyRuntimeError, _>(format!("Failed to end render pass: {}", e)))?
            .copy_image_to_buffer(vulkano::command_buffer::CopyImageToBufferInfo::image_buffer(img, buf.clone()))
            .map_err(|e| PyErr::new::<PyRuntimeError, _>(format!("Failed to copy image to buffer: {}", e)))?;

        let command_buffer = builder.build().map_err(|e| PyErr::new::<PyRuntimeError, _>(format!("Failed to build command buffer: {}", e)))?;

        let future = sync::now(self.device.clone())
            .then_execute(self.queue.clone(), command_buffer)
            .map_err(|e| PyErr::new::<PyRuntimeError, _>(format!("Failed to execute command buffer: {}", e)))?
            .then_signal_fence_and_flush()
            .map_err(|e| PyErr::new::<PyRuntimeError, _>(format!("Failed to flush future: {}", e)))?;

        future.wait(None).map_err(|e| PyErr::new::<PyRuntimeError, _>(format!("Failed to wait on future: {}", e)))?;

        let buffer_content = buf.read().map_err(|e| PyErr::new::<PyRuntimeError, _>(format!("Failed to read buffer: {}", e)))?;
        Ok(buffer_content.to_vec())
    }

    pub fn render_frame(&self, _camera_matrix: Vec<f32>) -> PyResult<Vec<u8>> {
        let image = Image::new(
            self.allocator.clone(),
            ImageCreateInfo {
                image_type: ImageType::Dim2d,
                format: Format::R8G8B8A8_UNORM,
                extent: [self.width, self.height, 1],
                usage: ImageUsage::COLOR_ATTACHMENT | ImageUsage::TRANSFER_SRC,
                ..Default::default()
            },
            AllocationCreateInfo {
                memory_type_filter: MemoryTypeFilter::PREFER_DEVICE,
                ..Default::default()
            },
        ).map_err(|e| PyErr::new::<PyRuntimeError, _>(format!("Failed to create image: {}", e)))?;

        let view = ImageView::new_default(image.clone())
            .map_err(|e| PyErr::new::<PyRuntimeError, _>(format!("Failed to create image view: {}", e)))?;

        let depth_buffer = Image::new(
            self.allocator.clone(),
            ImageCreateInfo {
                image_type: ImageType::Dim2d,
                format: Format::D16_UNORM,
                extent: [self.width, self.height, 1],
                usage: ImageUsage::DEPTH_STENCIL_ATTACHMENT,
                ..Default::default()
            },
            AllocationCreateInfo {
                memory_type_filter: MemoryTypeFilter::PREFER_DEVICE,
                ..Default::default()
            },
        ).map_err(|e| PyErr::new::<PyRuntimeError, _>(format!("Failed to create depth buffer: {}", e)))?;

        let depth_view = ImageView::new_default(depth_buffer.clone())
            .map_err(|e| PyErr::new::<PyRuntimeError, _>(format!("Failed to create depth buffer view: {}", e)))?;

        let framebuffer = Framebuffer::new(
            self.render_pass.clone(),
            FramebufferCreateInfo {
                attachments: vec![view, depth_view],
                ..Default::default()
            },
        ).map_err(|e| PyErr::new::<PyRuntimeError, _>(format!("Failed to create framebuffer: {}", e)))?;

        let mut builder = AutoCommandBufferBuilder::primary(
            &self.command_buffer_allocator,
            self.queue.queue_family_index(),
            CommandBufferUsage::OneTimeSubmit,
        ).map_err(|e| PyErr::new::<PyRuntimeError, _>(format!("Failed to create command buffer: {}", e)))?;

        // Create a dummy triangle
        let vertex1 = crate::renderer::PositionVertex { position: [-0.5, -0.5, 0.0] };
        let vertex2 = crate::renderer::PositionVertex { position: [ 0.5, -0.5, 0.0] };
        let vertex3 = crate::renderer::PositionVertex { position: [ 0.0,  0.5, 0.0] };
        let vertex_buffer = Buffer::from_iter(
            self.allocator.clone(),
            BufferCreateInfo {
                usage: BufferUsage::VERTEX_BUFFER,
                ..Default::default()
            },
            AllocationCreateInfo {
                memory_type_filter: MemoryTypeFilter::PREFER_HOST | MemoryTypeFilter::HOST_SEQUENTIAL_WRITE,
                ..Default::default()
            },
            vec![vertex1, vertex2, vertex3],
        ).map_err(|e| PyErr::new::<PyRuntimeError, _>(format!("Failed to create vertex buffer: {}", e)))?;

        let scalar1 = crate::renderer::ScalarVertex { scalar: 0.0 };
        let scalar2 = crate::renderer::ScalarVertex { scalar: 0.5 };
        let scalar3 = crate::renderer::ScalarVertex { scalar: 1.0 };
        let scalar_buffer = Buffer::from_iter(
            self.allocator.clone(),
            BufferCreateInfo {
                usage: BufferUsage::VERTEX_BUFFER,
                ..Default::default()
            },
            AllocationCreateInfo {
                memory_type_filter: MemoryTypeFilter::PREFER_HOST | MemoryTypeFilter::HOST_SEQUENTIAL_WRITE,
                ..Default::default()
            },
            vec![scalar1, scalar2, scalar3],
        ).map_err(|e| PyErr::new::<PyRuntimeError, _>(format!("Failed to create scalar buffer: {}", e)))?;

        let buf = Buffer::from_iter(
            self.allocator.clone(),
            BufferCreateInfo {
                usage: BufferUsage::TRANSFER_DST,
                ..Default::default()
            },
            AllocationCreateInfo {
                memory_type_filter: MemoryTypeFilter::PREFER_HOST | MemoryTypeFilter::HOST_RANDOM_ACCESS,
                ..Default::default()
            },
            (0..self.width * self.height * 4).map(|_| 0u8),
        ).map_err(|e| PyErr::new::<PyRuntimeError, _>(format!("Failed to create output buffer: {}", e)))?;

        builder
            .begin_render_pass(
                RenderPassBeginInfo {
                    clear_values: vec![Some([0.1, 0.2, 0.3, 1.0].into()), Some(1f32.into())],
                    ..RenderPassBeginInfo::framebuffer(framebuffer)
                },
                SubpassBeginInfo {
                    contents: SubpassContents::Inline,
                    ..Default::default()
                },
            )
            .map_err(|e| PyErr::new::<PyRuntimeError, _>(format!("Failed to begin render pass: {}", e)))?
            .bind_pipeline_graphics(self.pipeline.clone())
            .unwrap()
            .bind_vertex_buffers(0, vertex_buffer.clone())
            .unwrap()
            .bind_vertex_buffers(1, scalar_buffer.clone())
            .unwrap()
            .draw(3, 1, 0, 0)
            .unwrap();
        
        builder
            .end_render_pass(Default::default())
            .map_err(|e| PyErr::new::<PyRuntimeError, _>(format!("Failed to end render pass: {}", e)))?
            .copy_image_to_buffer(vulkano::command_buffer::CopyImageToBufferInfo::image_buffer(image, buf.clone()))
            .map_err(|e| PyErr::new::<PyRuntimeError, _>(format!("Failed to copy image to buffer: {}", e)))?;

        let command_buffer = builder.build().unwrap();

        let future = sync::now(self.device.clone())
            .then_execute(self.queue.clone(), command_buffer)
            .unwrap()
            .then_signal_fence_and_flush()
            .unwrap();

        future.wait(None).unwrap();

        let buffer_content = buf.read().map_err(|e| PyErr::new::<PyRuntimeError, _>(format!("Failed to read buffer: {}", e)))?;
        Ok(buffer_content.to_vec())
    }
}
