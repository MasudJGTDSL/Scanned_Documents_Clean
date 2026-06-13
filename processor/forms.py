from django import forms


class ProcessFolderForm(forms.Form):
    source_folder = forms.CharField(
        label='Source Image Folder',
        max_length=512,
        widget=forms.TextInput(attrs={
            'id': 'source_folder',
            'placeholder': 'e.g. E:\\PRL Info',
            'autocomplete': 'off',
        }),
        help_text='Enter the full path to the folder containing scanned images (.jpg, .png, .jpeg).',
    )
    output_folder = forms.CharField(
        label='Output Folder (optional)',
        max_length=512,
        required=False,
        widget=forms.TextInput(attrs={
            'id': 'output_folder',
            'placeholder': 'Leave blank to auto-create "cleaned_pdf_files" inside source folder',
            'autocomplete': 'off',
        }),
        help_text='Leave blank to save output inside the source folder automatically.',
    )

    def clean_source_folder(self):
        import os
        path = self.cleaned_data['source_folder'].strip()
        if not os.path.isdir(path):
            raise forms.ValidationError(f'The folder does not exist: {path}')
        return path

    def clean_output_folder(self):
        path = self.cleaned_data.get('output_folder', '').strip()
        return path if path else None
