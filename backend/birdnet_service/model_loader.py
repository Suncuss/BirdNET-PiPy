try:
    import tflite_runtime.interpreter as tflite
except ImportError:
    from tensorflow import lite as tflite

# Now you can use tflite as usual in your code

class ModelLoader:
    def __init__(self, model_path, meta_model_path, labels_path):
        self.model_path = model_path
        self.meta_model_path = meta_model_path
        self.labels_path = labels_path

        self.model = None
        self.meta_model = None
        
        self.input_layer_index = None
        self.output_layer_index = None
        self.meta_input_layer_index = None
        self.meta_output_layer_index = None

        self.labels = None

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