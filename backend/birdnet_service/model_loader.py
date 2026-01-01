import json
import logging

try:
    import tflite_runtime.interpreter as tflite
except ImportError:
    from tensorflow import lite as tflite

logger = logging.getLogger(__name__)


class ModelLoader:
    def __init__(self, model_path, meta_model_path, labels_path, ebird_codes_path=None):
        self.model_path = model_path
        self.meta_model_path = meta_model_path
        self.labels_path = labels_path
        self.ebird_codes_path = ebird_codes_path

        self.model = None
        self.meta_model = None

        self.input_layer_index = None
        self.output_layer_index = None
        self.meta_input_layer_index = None
        self.meta_output_layer_index = None

        self.labels = None
        self.ebird_codes = None

    def load_model(self):
        if self.model is None:
            self.model = tflite.Interpreter(model_path=self.model_path, num_threads=2)
            self.model.allocate_tensors()
            self.input_layer_index = self.model.get_input_details()[0]['index']
            self.output_layer_index = self.model.get_output_details()[0]['index']
        return self.model

    def load_meta_model(self):
        if self.meta_model is None:
            self.meta_model = tflite.Interpreter(model_path=self.meta_model_path)
            self.meta_model.allocate_tensors()
            self.meta_input_layer_index = self.meta_model.get_input_details()[0]['index']
            self.meta_output_layer_index = self.meta_model.get_output_details()[0]['index']
        return self.meta_model

    def load_labels(self):
        # TODO: dynamically load labels from depends on config
        with open(self.labels_path, 'r') as f:
            self.labels = [line.strip() for line in f.readlines()]
        return self.labels

    def load_ebird_codes(self):
        """Load eBird species codes mapping from JSON file.

        Returns empty dict if file is missing or invalid.
        """
        if self.ebird_codes is not None:
            return self.ebird_codes

        if not self.ebird_codes_path:
            self.ebird_codes = {}
            return self.ebird_codes

        try:
            with open(self.ebird_codes_path, 'r', encoding='utf-8') as f:
                self.ebird_codes = json.load(f)
            logger.info(f"Loaded {len(self.ebird_codes)} eBird species codes")
        except FileNotFoundError:
            logger.warning(f"eBird codes file not found: {self.ebird_codes_path}")
            self.ebird_codes = {}
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in eBird codes file: {e}")
            self.ebird_codes = {}

        return self.ebird_codes

    def get_ebird_code(self, scientific_name):
        """Get eBird species code for a scientific name.

        Args:
            scientific_name: Scientific name of the species (e.g., "Turdus migratorius")

        Returns:
            eBird species code (e.g., "amerob") or None if not found
        """
        if self.ebird_codes is None:
            self.load_ebird_codes()
        return self.ebird_codes.get(scientific_name)