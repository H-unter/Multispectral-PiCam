"""Data model, persistence, and analysis for multispectral image cubes."""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Iterable

import cv2
import numpy as np

try:
	from .SpectralChannel import SpectralChannel
except ImportError:
	import sys
	print("diddy")
	project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
	if project_dir not in sys.path:
		sys.path.insert(0, project_dir)
	from models.SpectralChannel import SpectralChannel


class MultispectralImage:
	"""Own a multispectral cube, its channel metadata, and its file formats.

	Cube data is stored as ``height x width x spectral_channel``. Each spectral
	slice is expected to be a monochrome image.
	"""

	SCHEMA_VERSION = 1

	def __init__(
		self,
		data: np.ndarray,
		channel_names: list[str],
		metadata: dict[str, Any] | None = None,
	) -> None:
		data = np.asarray(data)
		if data.ndim != 3:
			raise ValueError(f"Expected a 3D cube, received shape {data.shape}")
		if data.shape[-1] != len(channel_names):
			raise ValueError(
				"The number of channel names must match the cube's final dimension"
			)
		if len(set(channel_names)) != len(channel_names):
			raise ValueError("Channel names must be unique")

		self.data = data
		self.channel_names = list(channel_names)
		self.metadata = metadata or {}

	@classmethod
	def from_layers(
		cls,
		layers: Iterable[tuple[str, np.ndarray]],
		channels: Iterable[SpectralChannel] | None = None,
		metadata: dict[str, Any] | None = None,
	) -> "MultispectralImage":
		"""Build a cube from named monochrome layers in capture order."""
		layer_list = list(layers)
		if not layer_list:
			raise ValueError("At least one spectral layer is required")

		names = [name for name, _ in layer_list]
		arrays = [np.asarray(array) for _, array in layer_list]
		first_shape = arrays[0].shape
		if any(array.shape != first_shape for array in arrays):
			raise ValueError("All spectral layers must have the same dimensions")
		if any(array.ndim != 2 for array in arrays):
			raise ValueError("Spectral layers must be monochrome 2D arrays")

		channel_metadata = []
		channel_lookup = {channel.name: channel for channel in channels or []}
		for index, name in enumerate(names):
			channel = channel_lookup.get(name)
			channel_metadata.append(
				{
					"name": name,
					"index": index,
					"configuration": cls._serialize_channel(channel),
				}
			)

		capture_metadata = dict(metadata or {})
		capture_metadata.setdefault("schema_version", cls.SCHEMA_VERSION)
		capture_metadata.setdefault(
			"created_at", datetime.now(timezone.utc).isoformat()
		)
		capture_metadata["data_shape"] = list(
			(first_shape[0], first_shape[1], len(arrays))
		)
		capture_metadata["data_dtype"] = str(np.result_type(*arrays))
		capture_metadata["channels"] = channel_metadata
		capture_metadata.setdefault("pixel_processing", "mean of RGB channels")

		return cls(np.stack(arrays, axis=-1), names, capture_metadata)

	@staticmethod
	def _serialize_channel(channel: SpectralChannel | None) -> dict[str, Any] | None:
		if channel is None:
			return None
		return {
			"led": asdict(channel.led) if channel.led is not None else None,
			"driver": asdict(channel.driver),
			"camera": asdict(channel.camera),
		}

	def channel(self, name: str) -> np.ndarray:
		"""Return one monochrome spectral slice by channel name."""
		try:
			index = self.channel_names.index(name)
		except ValueError as error:
			raise KeyError(f"Unknown spectral channel: {name}") from error
		return self.data[..., index]

	def channel_statistics(self) -> dict[str, dict[str, float]]:
		"""Return basic relative-intensity statistics for every channel."""
		return {
			name: {
				"mean": float(np.mean(self.channel(name))),
				"minimum": float(np.min(self.channel(name))),
				"maximum": float(np.max(self.channel(name))),
				"standard_deviation": float(np.std(self.channel(name))),
			}
			for name in self.channel_names
		}

	def export_npz(self, path: str) -> None:
		"""Export data, channel order, and JSON metadata as one NPZ package."""
		np.savez_compressed(
			path,
			data=self.data,
			bands=np.asarray(self.channel_names),
			metadata=np.asarray(json.dumps(self.metadata)),
		)

	def export_jpgs(self, target_dir: str) -> None:
		"""Export one monochrome JPG and a JSON metadata file per cube package."""
		os.makedirs(target_dir, exist_ok=True)
		for index, name in enumerate(self.channel_names):
			safe_name = name.replace(os.sep, "_").replace(" ", "_")
			output_file = os.path.join(target_dir, f"capture_{safe_name}.jpg")
			image = np.clip(self.data[..., index], 0, 255).astype(np.uint8)
			if not cv2.imwrite(output_file, image):
				raise IOError(f"Could not write {output_file}")

	def export(self, target: str, mode: str) -> None:
		"""Export using ``npz`` or ``jpg`` mode."""
		if mode == "npz" or mode == "hypercube":
			self.export_npz(target)
		elif mode == "jpg":
			self.export_jpgs(target)
		else:
			raise ValueError(f"Unknown multispectral export mode: {mode}")

	@classmethod
	def import_npz(cls, path: str) -> "MultispectralImage":
		"""Load a cube and its metadata from an NPZ package."""
		with np.load(path, allow_pickle=False) as package:
			data = package["data"]
			names = [str(name) for name in package["bands"].tolist()]
			metadata_value = package["metadata"].item()
			metadata = json.loads(str(metadata_value))
		return cls(data, names, metadata)


if __name__ == "__main__":
	import sys

	project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
	if project_dir not in sys.path:
		sys.path.insert(0, project_dir)

	from camera_hardware import CameraHardware

	output_dir = os.path.join(project_dir, "images")
	export_mode = "npz"
	hardware = CameraHardware()
	os.makedirs(output_dir, exist_ok=True)
	try:
		hardware.setup()
		image = hardware.acquire_spectral_cube()
		if export_mode in {"hypercube", "npz"}:
			image.export_npz(os.path.join(output_dir, "multispectral_cube.npz"))
		else:
			image.export_jpgs(output_dir)
	except Exception as error:
		print(f"\n[ERROR] Failed multispectral block acquisition: {error}", file=sys.stderr)
		sys.exit(1)
	finally:
		hardware.teardown()
