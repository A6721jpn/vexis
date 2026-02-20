use pyo3::prelude::*;
use pyo3::exceptions::PyValueError;
use std::fs::File;
use std::path::Path;
use memmap2::{Mmap, MmapOptions};
use std::sync::Arc;
use byteorder::{ByteOrder, LittleEndian, BigEndian};

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum Endianness {
    Little,
    Big,
}

#[derive(Debug, Clone)]
pub struct Block {
    pub tag: u32,
    pub offset: usize, // offset to the block data (after tag + size)
    pub size: usize,
    pub children: Vec<Block>,
}

#[derive(Debug, Clone)]
pub struct VarInfo {
    pub name: String,
    pub type_id: u32,
    pub format_id: u32,
    pub index: usize,
}

#[pyclass]
pub struct XpltFastParser {
    mmap: Arc<memmap2::Mmap>,
    endian: Endianness,
    pub num_nodes: usize,
    pub num_elements: usize,
    
    node_vars: Vec<VarInfo>,
    domain_vars: Vec<VarInfo>,
    
    // Step index -> offset to State block (0x02000000)
    step_offsets: Vec<usize>,
}

#[pymethods]
impl XpltFastParser {
    #[new]
    pub fn new(filepath: &str) -> PyResult<Self> {
        let path = Path::new(filepath);
        if !path.exists() {
            return Err(pyo3::exceptions::PyFileNotFoundError::new_err(format!(
                "File not found: {}",
                filepath
            )));
        }

        let file = File::open(path)?;
        let mmap = unsafe { MmapOptions::new().map(&file)? };

        if mmap.len() < 4 {
            return Err(PyValueError::new_err("File too small"));
        }

        let magic = &mmap[0..4];
        let endian = if magic == b"BEF\0" {
            Endianness::Little
        } else if magic == b"\0FEB" {
            Endianness::Big
        } else {
            return Err(PyValueError::new_err("Invalid FEBio signature"));
        };
        
        let root_blocks = Self::parse_blocks(&mmap, 4, mmap.len(), endian, 0);
        
        // Metadata extraction: try 0x01010002 (Header) then 0x01041101 (Node Header -> size)
        let num_nodes = if let Some(n_block) = Self::find_block(&root_blocks, 0x01010002) {
            Self::read_u32(&mmap, n_block.offset, endian) as usize
        } else if let Some(n_block) = Self::find_block(&root_blocks, 0x01041101) {
            Self::read_u32(&mmap, n_block.offset, endian) as usize
        } else {
            0
        };

        let mut num_elements = 0;
        let mut domains = Vec::new();
        Self::find_blocks(&root_blocks, 0x01042100, &mut domains); // Find all Domain blocks
        for domain in &domains {
            if let Some(e_block) = Self::find_block(&domain.children, 0x01032104) {
                num_elements += Self::read_u32(&mmap, e_block.offset, endian) as usize;
            }
        }

        let mut node_vars = Vec::new();
        let mut domain_vars = Vec::new();
        let mut step_offsets = Vec::new();

        // Dictionary extraction
        if let Some(dict_block) = Self::find_block(&root_blocks, 0x01020000) {
            for dict_section in &dict_block.children {
                let is_node = dict_section.tag == 0x01023000;
                let is_domain = dict_section.tag == 0x01024000;
                if is_node || is_domain {
                    let mut var_id_counter = 1;
                    for item in &dict_section.children {
                        if item.tag == 0x01020001 { // Dictionary item
                            let mut name = String::new();
                            let mut type_id = 0;
                            let mut format_id = 0;
                            for prop in &item.children {
                                if prop.tag == 0x01020002 { type_id = Self::read_u32(&mmap, prop.offset, endian); }
                                if prop.tag == 0x01020003 { format_id = Self::read_u32(&mmap, prop.offset, endian); }
                                if prop.tag == 0x01020004 { 
                                    let mut end = prop.offset;
                                    while end < prop.offset + prop.size && mmap[end] != 0 {
                                        end += 1;
                                    }
                                    name = String::from_utf8_lossy(&mmap[prop.offset..end]).into_owned();
                                }
                            }
                            if is_node {
                                node_vars.push(VarInfo{name, type_id, format_id, index: var_id_counter});
                            } else {
                                domain_vars.push(VarInfo{name, type_id, format_id, index: var_id_counter});
                            }
                            var_id_counter += 1;
                        }
                    }
                }
            }
        }

        for b in &root_blocks {
            if b.tag == 0x02000000 { // State
                step_offsets.push(b.offset - 8);
            }
        }

        Ok(XpltFastParser {
            mmap: Arc::new(mmap),
            endian,
            num_nodes,
            num_elements,
            node_vars,
            domain_vars,
            step_offsets,
        })
    }

    pub fn get_num_nodes(&self) -> usize { self.num_nodes }
    pub fn get_num_elements(&self) -> usize { self.num_elements }
    pub fn get_num_steps(&self) -> usize { self.step_offsets.len() }
    
    pub fn get_node_vars(&self) -> Vec<String> {
        self.node_vars.iter().map(|v| v.name.clone()).collect()
    }

    pub fn get_domain_vars(&self) -> Vec<String> {
        self.domain_vars.iter().map(|v| v.name.clone()).collect()
    }

    // Extract a node variable as a float array. 
    // Uses PyO3 'py' token to safely allocate Python structures
    pub fn get_node_data<'py>(&self, py: Python<'py>, step_idx: usize, var_name: &str) -> PyResult<Bound<'py, pyo3::types::PyAny>> {
        if step_idx >= self.step_offsets.len() {
            return Err(PyValueError::new_err("Invalid step index"));
        }
        let var_info = self.node_vars.iter().find(|v| v.name == var_name);
        if var_info.is_none() {
            return Err(PyValueError::new_err(format!("Node variable '{}' not found", var_name)));
        }
        let var_id = var_info.unwrap().index as u32; // In FEBio, the Variable ID matches the 1-based index in the dictionary
        let item_type = var_info.unwrap().type_id;

        // Parse State Block
        let offset = self.step_offsets[step_idx];
        let state_blocks = Self::parse_blocks(&self.mmap, offset, self.mmap.len(), self.endian, 0);
        
        let mut raw_data = None;

        for b in &state_blocks {
            if b.tag == 0x02000000 { // State
                for c in &b.children {
                    if c.tag == 0x02020000 { // State Data
                        for sd in &c.children {
                            if sd.tag == 0x02020300 { // Node Data
                                for sv in &sd.children {
                                    if sv.tag == 0x02020001 { // State Variable
                                        let mut this_var_id = 0;
                                        let mut this_data = None;
                                        for p in &sv.children {
                                            if p.tag == 0x02020002 { this_var_id = Self::read_u32(&self.mmap, p.offset, self.endian); }
                                            if p.tag == 0x02020003 { this_data = Some(p); }
                                        }
                                        if this_var_id == var_id {
                                            raw_data = this_data.cloned();
                                            break;
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        if let Some(data_block) = raw_data {
            // Data layout: [region_id: u32][size: u32][values...]
            let comp_count = match item_type {
                0 => 1, // FLOAT
                1 => 3, // VEC3F
                2 => 6, // MAT3FS
                _ => 1,
            };
            
            // Assume single region for nodes usually
            let mut ptr = data_block.offset;
            let end = data_block.offset + data_block.size;
            
            // We just flatten to a 1D or 2D PyArray
            let mut values_flat = Vec::with_capacity(self.num_nodes * comp_count);
            
            while ptr + 8 <= end {
                let _region_id = Self::read_u32(&self.mmap, ptr, self.endian);
                let size = Self::read_u32(&self.mmap, ptr + 4, self.endian) as usize;
                ptr += 8;
                if ptr + size > end { break; }
                
                let num_floats = size / 4;
                for i in 0..num_floats {
                    if ptr + i * 4 + 4 <= end {
                        let f = match self.endian {
                            Endianness::Little => LittleEndian::read_f32(&self.mmap[ptr + i * 4 .. ptr + i * 4 + 4]),
                            Endianness::Big => BigEndian::read_f32(&self.mmap[ptr + i * 4 .. ptr + i * 4 + 4]),
                        };
                        values_flat.push(f);
                    }
                }
                ptr += size;
            }
            
            if comp_count == 1 {
                let py_array = pyo3::types::PyList::new_bound(py, values_flat.iter());
                Ok(py_array.into_any())
            } else {
                let num_items = values_flat.len() / comp_count;
                let mut nested = Vec::with_capacity(num_items);
                for i in 0..num_items {
                    let chunk = &values_flat[i * comp_count .. (i+1) * comp_count];
                    let py_chunk = pyo3::types::PyList::new_bound(py, chunk.iter());
                    nested.push(py_chunk);
                }
                let py_array = pyo3::types::PyList::new_bound(py, nested.iter());
                Ok(py_array.into_any())
            }
            
        } else {
            Err(PyValueError::new_err("Data not found for variable in this step"))
        }
    }

    // Extract a domain variable as a float array. 
    pub fn get_domain_data<'py>(&self, py: Python<'py>, step_idx: usize, var_name: &str) -> PyResult<Bound<'py, pyo3::types::PyAny>> {
        if step_idx >= self.step_offsets.len() {
            return Err(PyValueError::new_err("Invalid step index"));
        }
        let var_info = self.domain_vars.iter().find(|v| v.name == var_name);
        if var_info.is_none() {
            return Err(PyValueError::new_err(format!("Domain variable '{}' not found", var_name)));
        }
        let var_id = var_info.unwrap().index as u32; 
        let item_type = var_info.unwrap().type_id;

        let offset = self.step_offsets[step_idx];
        let state_blocks = Self::parse_blocks(&self.mmap, offset, self.mmap.len(), self.endian, 0);
        
        let mut raw_data = None;

        for b in &state_blocks {
            if b.tag == 0x02000000 { // State
                for c in &b.children {
                    if c.tag == 0x02020000 { // State Data
                        for sd in &c.children {
                            if sd.tag == 0x02020400 { // Domain Data
                                for sv in &sd.children {
                                    if sv.tag == 0x02020001 { // State Variable
                                        let mut this_var_id = 0;
                                        let mut this_data = None;
                                        for p in &sv.children {
                                            if p.tag == 0x02020002 { this_var_id = Self::read_u32(&self.mmap, p.offset, self.endian); }
                                            if p.tag == 0x02020003 { this_data = Some(p); }
                                        }
                                        if this_var_id == var_id {
                                            raw_data = this_data.cloned();
                                            break;
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        if let Some(data_block) = raw_data {
            let comp_count = match item_type {
                0 => 1, // FLOAT
                1 => 3, // VEC3F
                2 => 6, // MAT3FS
                _ => 1,
            };
            
            let mut ptr = data_block.offset;
            let end = data_block.offset + data_block.size;
            
            // Collect all regions. In domain data, there is one array per domain.
            let mut values_flat = Vec::with_capacity(self.num_elements * comp_count);
            
            while ptr + 8 <= end {
                let _region_id = Self::read_u32(&self.mmap, ptr, self.endian);
                let size = Self::read_u32(&self.mmap, ptr + 4, self.endian) as usize;
                ptr += 8;
                if ptr + size > end { break; }
                
                let num_floats = size / 4;
                for i in 0..num_floats {
                    if ptr + i * 4 + 4 <= end {
                        let f = match self.endian {
                            Endianness::Little => LittleEndian::read_f32(&self.mmap[ptr + i * 4 .. ptr + i * 4 + 4]),
                            Endianness::Big => BigEndian::read_f32(&self.mmap[ptr + i * 4 .. ptr + i * 4 + 4]),
                        };
                        values_flat.push(f);
                    }
                }
                ptr += size;
            }
            
            if comp_count == 1 {
                let py_array = pyo3::types::PyList::new_bound(py, values_flat.iter());
                Ok(py_array.into_any())
            } else {
                let num_items = values_flat.len() / comp_count;
                let mut nested = Vec::with_capacity(num_items);
                for i in 0..num_items {
                    let chunk = &values_flat[i * comp_count .. (i+1) * comp_count];
                    let py_chunk = pyo3::types::PyList::new_bound(py, chunk.iter());
                    nested.push(py_chunk);
                }
                let py_array = pyo3::types::PyList::new_bound(py, nested.iter());
                Ok(py_array.into_any())
            }
            
        } else {
            Err(PyValueError::new_err("Data not found for variable in this step"))
        }
    }

    // Extract base node coordinates (0x01041001 -> array of VEC3F)
    pub fn get_base_coordinates<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, pyo3::types::PyAny>> {
        let root_blocks = Self::parse_blocks(&self.mmap, 4, self.mmap.len(), self.endian, 0);
        
        // Search for 0x01041001 (Node coords v1.0) or 0x01041200 (Node coords v2.0)
        let coords_block = if let Some(b) = Self::find_block(&root_blocks, 0x01041001) {
            Some(b)
        } else if let Some(b) = Self::find_block(&root_blocks, 0x01041200) {
            Some(b)
        } else {
            None
        };

        if let Some(block) = coords_block {
            let offset = block.offset;
            let size = block.size;
            
            // XPLT 1.0: simple array of f32 (num_nodes * 3)
            // XPLT 2.0: mixed int id + 3x f32 (num_nodes * 16 bytes)
            let (is_v2, item_size) = if block.tag == 0x01041200 { (true, 16) } else { (false, 12) };

            let num_items = size / item_size;
            let mut nested = Vec::with_capacity(num_items);
            
            for i in 0..num_items {
                let start = offset + i * item_size + (if is_v2 { 4 } else { 0 });
                let mut chunk = Vec::with_capacity(3);
                for j in 0..3 {
                    let poff = start + j * 4;
                    let f = match self.endian {
                        Endianness::Little => LittleEndian::read_f32(&self.mmap[poff .. poff + 4]),
                        Endianness::Big => BigEndian::read_f32(&self.mmap[poff .. poff + 4]),
                    };
                    chunk.push(f);
                }
                nested.push(pyo3::types::PyList::new_bound(py, chunk.iter()));
            }
            let py_array = pyo3::types::PyList::new_bound(py, nested.iter());
            Ok(py_array.into_any())
        } else {
            Err(PyValueError::new_err("Node coordinates block (0x01041001/0x01041200) not found"))
        }
    }

    // Extract element connectivity array from domain. 
    // Returns list of [elem_id, n1, n2, n3, n4...]
    pub fn get_domain_elements<'py>(&self, py: Python<'py>, domain_idx: usize) -> PyResult<Bound<'py, pyo3::types::PyAny>> {
        let root_blocks = Self::parse_blocks(&self.mmap, 4, self.mmap.len(), self.endian, 0);
        let mut domains = Vec::new();
        Self::find_blocks(&root_blocks, 0x01042100, &mut domains); // Find all Domain blocks

        if domain_idx >= domains.len() {
            return Err(PyValueError::new_err(format!("Invalid domain index. Found {} domains.", domains.len())));
        }

        let domain = domains[domain_idx];
        // Element items are 0x01042201 inside element list (0x01042200)
        let mut element_blocks = Vec::new();
        Self::find_blocks(&domain.children, 0x01042201, &mut element_blocks);

        let mut all_ints = Vec::new();
        for eb in &element_blocks {
            let offset = eb.offset;
            let size = eb.size;
            let num_ints = size / 4;
            for i in 0..num_ints {
                let v = match self.endian {
                    Endianness::Little => LittleEndian::read_u32(&self.mmap[offset + i * 4 .. offset + i * 4 + 4]),
                    Endianness::Big => BigEndian::read_u32(&self.mmap[offset + i * 4 .. offset + i * 4 + 4]),
                };
                all_ints.push(v);
            }
        }
        
        if !all_ints.is_empty() {
            let py_array = pyo3::types::PyList::new_bound(py, all_ints.iter());
            Ok(py_array.into_any())
        } else {
            Err(PyValueError::new_err("Elements (0x01042201) not found in domain"))
        }
    }
}

impl XpltFastParser {
    // Recursive search for a block
    fn find_block<'a>(blocks: &'a [Block], target_tag: u32) -> Option<&'a Block> {
        for b in blocks {
            if b.tag == target_tag {
                return Some(b);
            }
            if let Some(res) = Self::find_block(&b.children, target_tag) {
                return Some(res);
            }
        }
        None
    }

    // Find all blocks matching a tag
    fn find_blocks<'a>(blocks: &'a [Block], target_tag: u32, results: &mut Vec<&'a Block>) {
        for b in blocks {
            if b.tag == target_tag {
                results.push(b);
            }
            Self::find_blocks(&b.children, target_tag, results);
        }
    }

    fn read_u32(data: &[u8], offset: usize, endian: Endianness) -> u32 {
        if offset + 4 > data.len() { return 0; }
        match endian {
            Endianness::Little => LittleEndian::read_u32(&data[offset..offset+4]),
            Endianness::Big => BigEndian::read_u32(&data[offset..offset+4]),
        }
    }

    fn is_branch(tag: u32) -> bool {
        let branch_tags = [
            0x01000000, 0x01010000, 0x01020000, 0x01021000, 0x01022000, 0x01023000, 0x01024000, 0x01025000, 0x01020001,
            0x01030000, 0x01030001, 0x01040000, 0x01041000, 0x01041100, 0x01042000, 0x01042100, 0x01042101, 0x01042200,
            0x01043000, 0x01043100, 0x01043101, 0x01043200, 0x01044000, 0x01044100, 0x01045000, 0x01045100, 0x01050000,
            0x02000000, 0x02010000, 0x02020000, 0x02020300, 0x02020400, 0x02020001
        ];
        branch_tags.contains(&tag)
    }

    fn parse_blocks(data: &[u8], mut offset: usize, end_limit: usize, endian: Endianness, depth: usize) -> Vec<Block> {
        let mut blocks = Vec::new();
        while offset + 8 <= end_limit && offset + 8 <= data.len() {
            let tag = Self::read_u32(data, offset, endian);
            let size = Self::read_u32(data, offset + 4, endian) as usize;
            
            if offset + 8 + size > data.len() || offset + 8 + size > end_limit {
                break;
            }

            let mut children = Vec::new();
            if Self::is_branch(tag) && depth < 10 {
                children = Self::parse_blocks(data, offset + 8, offset + 8 + size, endian, depth + 1);
            }

            blocks.push(Block {
                tag,
                offset: offset + 8,
                size,
                children,
            });

            offset += 8 + size;
        }
        blocks
    }
}
