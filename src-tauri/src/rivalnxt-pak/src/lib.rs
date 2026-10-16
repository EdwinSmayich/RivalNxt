//! Writing and reading the small .pak files RivalNxt makes itself.
//!
//! The voice-subtitle feature writes two kinds: a subtitle mod (one JSON file
//! at a path the game does not read) and the combined subtitle file (one copy
//! of the game's Game.locres). Both are written the way the game's own mod
//! files are: pak version 11, path hash seed 0, nothing compressed, and the
//! index encrypted with the game's key -- every mod in the game's mods folder
//! has an encrypted index.

use pyo3::exceptions::{PyIOError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::PyBytes;
use std::fs::File;
use std::io::{BufReader, BufWriter};

fn builder(aes_key: Option<&str>) -> PyResult<repak::PakBuilder> {
    let mut builder = repak::PakBuilder::new();
    if let Some(key) = aes_key {
        let key: repak::utils::AesKey = key
            .parse()
            .map_err(|_| PyValueError::new_err(format!("invalid AES key: {key}")))?;
        builder = builder.key(key.0);
    }
    Ok(builder)
}

fn io_err(e: std::io::Error) -> PyErr {
    PyIOError::new_err(e.to_string())
}

fn pak_err(e: repak::Error) -> PyErr {
    PyIOError::new_err(e.to_string())
}

/// Write a pak. `entries` are (path inside the pak, contents).
#[pyfunction]
#[pyo3(signature = (pak_path, entries, aes_key = None, mount_point = "../../../"))]
fn write_pak(pak_path: &str, entries: Vec<(String, Vec<u8>)>, aes_key: Option<&str>, mount_point: &str) -> PyResult<()> {
    let file = File::create(pak_path).map_err(io_err)?;
    let mut writer = builder(aes_key)?.writer(BufWriter::new(file), repak::Version::V11, mount_point.to_string(), Some(0));
    for (path, data) in entries {
        writer.write_file(&path, false, data).map_err(pak_err)?;
    }
    writer.write_index().map_err(pak_err)?;
    Ok(())
}

/// The paths of the files in a pak.
#[pyfunction]
#[pyo3(signature = (pak_path, aes_key = None))]
fn list_pak_files(pak_path: &str, aes_key: Option<&str>) -> PyResult<Vec<String>> {
    let mut reader = BufReader::new(File::open(pak_path).map_err(io_err)?);
    let pak = builder(aes_key)?.reader(&mut reader).map_err(pak_err)?;
    Ok(pak.files())
}

/// One file out of a pak that is not compressed, by its path inside the pak.
#[pyfunction]
#[pyo3(signature = (pak_path, path, aes_key = None))]
fn read_pak_file<'py>(py: Python<'py>, pak_path: &str, path: &str, aes_key: Option<&str>) -> PyResult<Bound<'py, PyBytes>> {
    let mut reader = BufReader::new(File::open(pak_path).map_err(io_err)?);
    let pak = builder(aes_key)?.reader(&mut reader).map_err(pak_err)?;
    let data = pak.get(path, &mut reader).map_err(pak_err)?;
    Ok(PyBytes::new_bound(py, &data))
}

#[pymodule]
fn rivalnxt_pak(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(write_pak, m)?)?;
    m.add_function(wrap_pyfunction!(list_pak_files, m)?)?;
    m.add_function(wrap_pyfunction!(read_pak_file, m)?)?;
    Ok(())
}
