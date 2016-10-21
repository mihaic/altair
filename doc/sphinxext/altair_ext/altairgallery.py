import os
import shutil
import warnings
import json
import random
from operator import itemgetter

import jinja2

from subprocess import CalledProcessError

from docutils import nodes
from docutils.statemachine import ViewList
from docutils.parsers.rst.directives import flag

from sphinx.util.compat import Directive
from sphinx.util.nodes import nested_parse_with_titles

from .utils import strip_vl_extension, create_thumbnail, prev_this_next, dict_hash
from altair import Chart
from altair.examples import iter_examples_with_metadata


GALLERY_TEMPLATE = jinja2.Template(u"""
.. This document is auto-generated by the altair-gallery extension. Do not modify directly.

.. _{{ gallery_ref }}:

{{ title }}
{% for char in title %}-{% endfor %}

The following examples are automatically generated from
`Vega-Lite's Examples <http://vega.github.io/vega-lite/examples>`_

{% for group in examples|groupby('category') %}
* :ref:`gallery-category-{{ group.grouper }}`
{% endfor %}

{% for group in examples|groupby('category') %}

.. _gallery-category-{{ group.grouper }}:

{{ group.grouper }}
{% for char in group.grouper %}~{% endfor %}

{% for example in group.list %}
.. figure:: {{ image_dir }}/{{ example.name }}-thumb.png
    :target: {{ example.name }}.html
    :align: center

    :ref:`gallery_{{ example.name }}`
{% endfor %}

.. raw:: html

   <div style='clear:left;'></div>

{% endfor %}


.. toctree::
   :hidden:
{% for example in examples %}
   {{ example.name }}
{%- endfor %}
""")


MINIGALLERY_TEMPLATE = jinja2.Template(u"""
{% for example in examples %}
.. figure:: {{ image_dir }}/{{ example.name }}-thumb.png
    :target: {{ gallery_dir }}/{{ example.name }}.html
    :align: center
    :figclass: minigallery
    {% if width %}:width: {{ width }}{% endif %}

    {% if titles %}:ref:`gallery_{{ example.name }}`{% endif %}
{% endfor %}

.. raw:: html

   <div style='clear:left;'></div>

""")


EXAMPLE_TEMPLATE = jinja2.Template(u"""
.. This document is auto-generated by the altair-gallery extension. Do not modify directly.

.. _gallery_{{ name }}:

{{ title }}
{% for char in title %}-{% endfor %}

{% if prev_ref -%} < :ref:`{{ prev_ref }}` {% endif %}
| :ref:`{{ gallery_ref }}` |
{%- if next_ref %} :ref:`{{ next_ref }}` >{% endif %}

.. altair-plot::
    {% if code_below %}:code-below:{% endif %}

    from altair import *

    {{ code | indent(4) }}

.. toctree::
   :hidden:
""")


def populate_examples(num_examples=None, category=None, shuffle=False,
                      shuffle_seed=42, **kwargs):
    """Iterate through Altair examples and extract code"""

    examples = sorted(iter_examples_with_metadata(), key=itemgetter('name'))
    if category is not None:
        examples = [ex for ex in examples if ex['category'] == category]
    if shuffle:
        random.Random(shuffle_seed).shuffle(examples)
    if num_examples is not None:
        examples = examples[:num_examples]

    for prev_ex, example, next_ex in prev_this_next(examples):
        try:
            code = Chart.from_dict(example['spec']).to_altair()
        except Exception as e:
            warnings.warn('altair-gallery: example {0} produced an error:\n'
                          '{1}\n{2}'.format(example['name'], type(e), str(e)))
            code = '# (Altair JSON conversion failed).\nChart()'

        example['code'] = code

        if prev_ex:
            example['prev_ref'] = "gallery_{name}".format(**prev_ex)

        if next_ex:
            example['next_ref'] = "gallery_{name}".format(**next_ex)

        example['filename'] = '{0}.rst'.format(example['name'])
        example.update(kwargs)

    return examples


def make_images(image_dir, default_image, make_thumbnails=True):
    """Use nodejs to make images and (optionally) thumbnails"""

    can_save = Chart._png_output_available()
    if not can_save:
        warnings.warn('Node is not correctly configured: cannot save images.')

    if not os.path.exists(image_dir):
        os.makedirs(image_dir)

    # store hashes so that we know whether images need to be generated
    hash_file = os.path.join(image_dir, '_image_hashes.json')

    if os.path.exists(hash_file):
        with open(hash_file) as f:
            hashes = json.load(f)
    else:
        hashes = {}

    for example in iter_examples_with_metadata():
        filename = example['name'] + '.png'
        image_file = os.path.join(image_dir, filename)

        # check whether image already exists
        spec = example['spec']
        spec_hash = dict_hash(spec)
        if hashes.get(filename, '') == spec_hash:
            continue

        if can_save:
            chart = Chart.from_dict(spec)
            try:
                print('-> saving {0}'.format(image_file))
                chart.savechart(image_file)
            except CalledProcessError:
                warnings.warn('Node is not correctly configured: cannot save images.')
                can_save = False
                if not os.path.exists(image_file):
                    shutil.copyfile(default_image, image_file)
            else:
                hashes[filename] = spec_hash
        elif not os.path.exists(image_file):
            shutil.copyfile(default_image, image_file)

        if make_thumbnails:
            convert_pct = lambda x: 0.01 * int(x.strip('%'))
            params = example.get('galleryParameters', {})

            zoom = params.get('backgroundSize', '100%')
            if zoom == 'contains': zoom = '100%'
            zoom = convert_pct(zoom)

            #position = params.get('backgroundPosition', '0% 0%')
            #if position == 'left': position = '0% 0%'
            #xoffset, yoffset = map(convert_pct, position.split())

            thumb_file = os.path.join(image_dir, example['name'] + '-thumb.png')
            create_thumbnail(image_file, thumb_file, zoom=zoom)

    # Save hashes so we know whether we need to re-generate plots
    if hashes:
        with open(hash_file, 'w') as f:
            json.dump(hashes, f)


class AltairMiniGalleryDirective(Directive):
    has_content = False

    option_spec = {'size': int,
                   'shuffle': flag,
                   'seed': int,
                   'titles': bool,
                   'width': str}

    def run(self):
        size = self.options.get('size', 4)
        shuffle = 'shuffle' in self.options
        seed = self.options.get('seed', 42)
        titles = self.options.get('titles', False)
        width = self.options.get('width', None)

        env = self.state.document.settings.env
        app = env.app

        gallery_dir = app.builder.config.altair_gallery_dir
        gallery_ref = app.builder.config.altair_gallery_ref

        examples = populate_examples(shuffle=shuffle,
                                     shuffle_seed=seed,
                                     num_examples=size,
                                     gallery_dir=gallery_dir,
                                     gallery_ref=gallery_ref,
                                     code_below=True)

        include = MINIGALLERY_TEMPLATE.render(image_dir='/_images',
                                              gallery_dir=gallery_dir,
                                              examples=examples,
                                              titles=titles,
                                              width=width)

        # parse and return documentation
        result = ViewList()
        for line in include.split('\n'):
            result.append(line, "<altair-minigallery>")
        node = nodes.paragraph()
        node.document = self.state.document
        nested_parse_with_titles(self.state, result, node)

        return node.children


def main(app):
    gallery_dir = app.builder.config.altair_gallery_dir
    target_dir = os.path.join(app.builder.srcdir, gallery_dir)
    image_dir = os.path.join(app.builder.srcdir, '_images')

    gallery_ref = app.builder.config.altair_gallery_ref
    gallery_title = app.builder.config.altair_gallery_title
    examples = populate_examples(gallery_ref=gallery_ref,
                                 code_below=True)

    if not os.path.exists(target_dir):
        os.makedirs(target_dir)

    # Make the images
    default_image = os.path.join(app.builder.srcdir,
                                 '_static', 'gray-square.png')
    make_images(image_dir, default_image)

    # Write the gallery index file
    with open(os.path.join(target_dir, 'index.rst'), 'w') as f:
        f.write(GALLERY_TEMPLATE.render(title=gallery_title,
                                        examples=examples,
                                        image_dir='/_images',
                                        gallery_ref=gallery_ref))

    # Write the individual example files
    for example in examples:
        with open(os.path.join(target_dir, example['filename']), 'w') as f:
            f.write(EXAMPLE_TEMPLATE.render(example))


def setup(app):
    app.connect('builder-inited', main)
    app.add_stylesheet('altair-gallery.css')
    app.add_config_value('altair_gallery_dir', 'gallery', 'env')
    app.add_config_value('altair_gallery_ref', 'example-gallery', 'env')
    app.add_config_value('altair_gallery_title', 'Example Gallery', 'env')
    app.add_directive_to_domain('py', 'altair-minigallery', AltairMiniGalleryDirective)