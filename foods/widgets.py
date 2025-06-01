from django import forms
from django.utils.safestring import mark_safe

class InputGroupWithLabelWidget(forms.TextInput):
    def __init__(self, label_text=None, attrs=None):
        attrs = attrs or {}
        attrs.setdefault('class', 'form-control')
        self.label_text = label_text
        super().__init__(attrs)

    def render(self, name, value, attrs=None, renderer=None):
        input_html = super().render(name, value, attrs, renderer)
        html = f'''
        <div class="input-group mb-3">
            <span class="input-group-text">{self.label_text}</span>
            {input_html}
        </div>
        '''
        return mark_safe(html)

