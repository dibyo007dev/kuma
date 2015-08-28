from tower import ugettext_lazy as _lazy
from tower import ugettext as _

from django import forms
from django.conf import settings
from django.forms.widgets import CheckboxSelectMultiple


from kuma.contentflagging.forms import ContentFlagForm
import kuma.wiki.content
from kuma.core.form_fields import StrippedCharField
from .constants import (SLUG_CLEANSING_RE, SLUG_INVALID_CHARS_RE,
                        SLUG_INVALID_CHARS_VALIDATION_RE,
                        DOCUMENT_PATH_RE, REVIEW_FLAG_TAGS,
                        LOCALIZATION_FLAG_TAGS, RESERVED_SLUGS_RES)
from .models import (Document, Revision,
                     valid_slug_parent)


TITLE_REQUIRED = _lazy(u'Please provide a title.')
TITLE_SHORT = _lazy(u'The title is too short (%(show_value)s characters). '
                    u'It must be at least %(limit_value)s characters.')
TITLE_LONG = _lazy(u'Please keep the length of the title to %(limit_value)s '
                   u'characters or less. It is currently %(show_value)s '
                   u'characters.')
TITLE_PLACEHOLDER = _lazy(u'Name Your Article')
SLUG_REQUIRED = _lazy(u'Please provide a slug.')
SLUG_INVALID = _lazy(u'The slug provided is not valid.')
SLUG_SHORT = _lazy(u'The slug is too short (%(show_value)s characters). '
                   u'It must be at least %(limit_value)s characters.')
SLUG_LONG = _lazy(u'Please keep the length of the slug to %(limit_value)s '
                  u'characters or less. It is currently %(show_value)s '
                  u'characters.')
SUMMARY_REQUIRED = _lazy(u'Please provide a summary.')
SUMMARY_SHORT = _lazy(u'The summary is too short (%(show_value)s characters). '
                      u'It must be at least %(limit_value)s characters.')
SUMMARY_LONG = _lazy(u'Please keep the length of the summary to '
                     u'%(limit_value)s characters or less. It is currently '
                     u'%(show_value)s characters.')
CONTENT_REQUIRED = _lazy(u'Please provide content.')
CONTENT_SHORT = _lazy(u'The content is too short (%(show_value)s characters). '
                      u'It must be at least %(limit_value)s characters.')
CONTENT_LONG = _lazy(u'Please keep the length of the content to '
                     u'%(limit_value)s characters or less. It is currently '
                     u'%(show_value)s characters.')
COMMENT_LONG = _lazy(u'Please keep the length of the comment to '
                     u'%(limit_value)s characters or less. It is currently '
                     u'%(show_value)s characters.')
SLUG_COLLIDES = _lazy(u'Another document with this slug already exists.')
OTHER_COLLIDES = _lazy(u'Another document with this metadata already exists.')

MIDAIR_COLLISION = _lazy(u'This document was modified while you were '
                         'editing it.')
MOVE_REQUIRED = _lazy(u"Changing this document's slug requires "
                      u"moving it and its children.")


class DocumentForm(forms.ModelForm):
    """Form to create/edit a document."""

    title = StrippedCharField(min_length=1, max_length=255,
                              widget=forms.TextInput(
                                  attrs={'placeholder': TITLE_PLACEHOLDER}),
                              label=_lazy(u'Title:'),
                              help_text=_lazy(u'Title of article'),
                              error_messages={'required': TITLE_REQUIRED,
                                              'min_length': TITLE_SHORT,
                                              'max_length': TITLE_LONG})

    slug = StrippedCharField(min_length=1, max_length=255,
                             widget=forms.TextInput(),
                             label=_lazy(u'Slug:'),
                             help_text=_lazy(u'Article URL'),
                             error_messages={'required': SLUG_REQUIRED,
                                             'min_length': SLUG_SHORT,
                                             'max_length': SLUG_LONG})

    category = forms.ChoiceField(choices=Document.CATEGORIES,
                                 initial=10,
                                 # Required for non-translations, which is
                                 # enforced in Document.clean().
                                 required=False,
                                 label=_lazy(u'Category:'),
                                 help_text=_lazy(u'Type of article'),
                                 widget=forms.HiddenInput())

    parent_topic = forms.ModelChoiceField(queryset=Document.objects.all(),
                                          required=False,
                                          label=_lazy(u'Parent:'))

    locale = forms.CharField(widget=forms.HiddenInput())

    def clean_slug(self):
        slug = self.cleaned_data['slug']
        if slug == '':
            # Default to the title, if missing.
            slug = self.cleaned_data['title']
        # check both for disallowed characters and match for the allowed
        if (SLUG_INVALID_CHARS_RE.search(slug) or
                not DOCUMENT_PATH_RE.search(slug)):
            raise forms.ValidationError(SLUG_INVALID)
        # Guard against slugs that match urlpatterns
        for pattern in RESERVED_SLUGS_RES:
            if pattern.match(slug):
                raise forms.ValidationError(SLUG_INVALID)
        return slug

    class Meta:
        model = Document
        fields = ('title', 'slug', 'category', 'locale')

    def save(self, parent_doc, **kwargs):
        """Persist the Document form, and return the saved Document."""
        doc = super(DocumentForm, self).save(commit=False, **kwargs)
        doc.parent = parent_doc
        if 'parent_topic' in self.cleaned_data:
            doc.parent_topic = self.cleaned_data['parent_topic']
        doc.save()
        # not strictly necessary since we didn't change
        # any m2m data since we instantiated the doc
        self.save_m2m()
        return doc


class RevisionForm(forms.ModelForm):
    """Form to create new revisions."""

    title = StrippedCharField(min_length=1, max_length=255,
                              required=False,
                              widget=forms.TextInput(
                                  attrs={'placeholder': TITLE_PLACEHOLDER}),
                              label=_lazy(u'Title:'),
                              help_text=_lazy(u'Title of article'),
                              error_messages={'required': TITLE_REQUIRED,
                                              'min_length': TITLE_SHORT,
                                              'max_length': TITLE_LONG})
    slug = StrippedCharField(min_length=1, max_length=255,
                             required=False,
                             widget=forms.TextInput(),
                             label=_lazy(u'Slug:'),
                             help_text=_lazy(u'Article URL'),
                             error_messages={'required': SLUG_REQUIRED,
                                             'min_length': SLUG_SHORT,
                                             'max_length': SLUG_LONG})

    tags = StrippedCharField(required=False,
                             label=_lazy(u'Tags:'))

    keywords = StrippedCharField(required=False,
                                 label=_lazy(u'Keywords:'),
                                 help_text=_lazy(u'Affects search results'))

    summary = StrippedCharField(
        required=False,
        min_length=5, max_length=1000,
        widget=forms.Textarea(),
        label=_lazy(u'Search result summary:'),
        help_text=_lazy(u'Only displayed on search results page'),
        error_messages={'required': SUMMARY_REQUIRED,
                        'min_length': SUMMARY_SHORT,
                        'max_length': SUMMARY_LONG})

    content = StrippedCharField(
        min_length=5, max_length=300000,
        label=_lazy(u'Content:'),
        widget=forms.Textarea(),
        error_messages={'required': CONTENT_REQUIRED,
                        'min_length': CONTENT_SHORT,
                        'max_length': CONTENT_LONG})

    comment = StrippedCharField(required=False, label=_lazy(u'Comment:'))

    review_tags = forms.MultipleChoiceField(
        label=_("Tag this revision for review?"),
        widget=CheckboxSelectMultiple, required=False,
        choices=REVIEW_FLAG_TAGS)

    localization_tags = forms.MultipleChoiceField(
        label=_("Tag this revision for localization?"),
        widget=CheckboxSelectMultiple, required=False,
        choices=LOCALIZATION_FLAG_TAGS)

    current_rev = forms.CharField(required=False,
                                  widget=forms.HiddenInput())

    class Meta(object):
        model = Revision
        fields = ('title', 'slug', 'tags', 'keywords', 'summary', 'content',
                  'comment', 'based_on', 'toc_depth',
                  'render_max_age')

    def __init__(self, *args, **kwargs):
        self.section_id = kwargs.pop('section_id', None)
        self.is_iframe_target = kwargs.pop('is_iframe_target', None)


        super(RevisionForm, self).__init__(*args, **kwargs)
        self.fields['based_on'].widget = forms.HiddenInput()

        if self.instance and self.instance.pk:

            # Ensure both title and slug are populated from parent document, if
            # last revision didn't have them
            if not self.instance.title:
                self.initial['title'] = self.instance.document.title
            if not self.instance.slug:
                self.initial['slug'] = self.instance.document.slug

            content = self.instance.content
            if not self.instance.document.is_template:
                tool = kuma.wiki.content.parse(content)
                tool.injectSectionIDs()
                if self.section_id:
                    tool.extractSection(self.section_id)
                tool.filterEditorSafety()
                content = tool.serialize()
            self.initial['content'] = content

            self.initial['review_tags'] = list(self.instance.review_tags
                                                            .values_list('name',
                                                                         flat=True))
            self.initial['localization_tags'] = list(self.instance
                                                         .localization_tags
                                                         .values_list('name',
                                                                      flat=True))

        if self.section_id:
            self.fields['toc_depth'].required = False

    def _clean_collidable(self, name):
        value = self.cleaned_data[name]

        if self.is_iframe_target:
            # Since these collidables can change the URL of the page, changes
            # to them are ignored for an iframe submission
            return getattr(self.instance.document, name)

        error_message = {'slug': SLUG_COLLIDES}.get(name, OTHER_COLLIDES)
        try:
            existing_doc = Document.objects.get(
                locale=self.instance.document.locale,
                **{name: value})
            if self.instance and self.instance.document:
                if (not existing_doc.redirect_url() and
                        existing_doc.pk != self.instance.document.pk):
                    # There's another document with this value,
                    # and we're not a revision of it.
                    raise forms.ValidationError(error_message)
            else:
                # This document-and-revision doesn't exist yet, so there
                # shouldn't be any collisions at all.
                raise forms.ValidationError(error_message)

        except Document.DoesNotExist:
            # No existing document for this value, so we're good here.
            pass

        return value

    def clean_slug(self):
        # TODO: move this check somewhere else?
        # edits can come in without a slug, so default to the current doc slug
        if not self.cleaned_data['slug']:
            existing_slug = self.instance.document.slug
            self.cleaned_data['slug'] = self.instance.slug = existing_slug
        cleaned_slug = self._clean_collidable('slug')
        return cleaned_slug

    def clean_content(self):
        """Validate the content, performing any section editing if necessary"""
        content = self.cleaned_data['content']

        # If we're editing a section, we need to replace the section content
        # from the current revision.
        if self.section_id and self.instance and self.instance.document:
            # Make sure we start with content form the latest revision.
            full_content = self.instance.document.current_revision.content
            # Replace the section content with the form content.
            tool = kuma.wiki.content.parse(full_content)
            tool.replaceSection(self.section_id, content)
            content = tool.serialize()

        return content

    def clean_current_rev(self):
        """If a current revision is supplied in the form, compare it against
        what the document claims is the current revision. If there's a
        difference, then an edit has occurred since the form was constructed
        and we treat it as a mid-air collision."""
        current_rev = self.cleaned_data.get('current_rev', None)

        if not current_rev:
            # If there's no current_rev, just bail.
            return current_rev

        try:
            doc_current_rev = self.instance.document.current_revision.id
            if unicode(current_rev) != unicode(doc_current_rev):

                if (self.section_id and self.instance and
                        self.instance.document):
                    # This is a section edit. So, even though the revision has
                    # changed, it still might not be a collision if the section
                    # in particular hasn't changed.
                    orig_ct = (Revision.objects.get(pk=current_rev)
                               .get_section_content(self.section_id))
                    curr_ct = (self.instance.document.current_revision
                               .get_section_content(self.section_id))
                    if orig_ct != curr_ct:
                        # Oops. Looks like the section did actually get
                        # changed, so yeah this is a collision.
                        raise forms.ValidationError(MIDAIR_COLLISION)

                    return current_rev

                else:
                    # No section edit, so this is a flat-out collision.
                    raise forms.ValidationError(MIDAIR_COLLISION)

        except Document.DoesNotExist:
            # If there's no document yet, just bail.
            return current_rev

    def save_section(self, creator, document, **kwargs):
        """Save a section edit."""
        # This is separate because the logic is slightly different and
        # may need to evolve over time; a section edit doesn't submit
        # all the fields, and we need to account for that when we
        # construct the new Revision.

        old_rev = Document.objects.get(pk=self.instance.document.id).current_revision
        new_rev = super(RevisionForm, self).save(commit=False, **kwargs)
        new_rev.document = document
        new_rev.creator = creator
        new_rev.toc_depth = old_rev.toc_depth
        new_rev.save()
        new_rev.review_tags.set(*list(old_rev.review_tags
                                             .values_list('name', flat=True)))
        return new_rev

    def save(self, creator, document, **kwargs):
        """Persist me, and return the saved Revision.

        Take several other necessary pieces of data that aren't from the
        form.

        """
        if (self.section_id and self.instance and
                self.instance.document):
            return self.save_section(creator, document, **kwargs)
        # Throws a TypeError if somebody passes in a commit kwarg:
        new_rev = super(RevisionForm, self).save(commit=False, **kwargs)

        new_rev.document = document
        new_rev.creator = creator
        new_rev.toc_depth = self.cleaned_data['toc_depth']
        new_rev.save()
        new_rev.review_tags.set(*self.cleaned_data['review_tags'])
        new_rev.localization_tags.set(*self.cleaned_data['localization_tags'])
        return new_rev


class RevisionValidationForm(RevisionForm):
    """
    Created primarily to disallow slashes in slugs during validation
    """
    def clean_slug(self):
        original = self.cleaned_data['slug']
        if (original == u'' or
                SLUG_INVALID_CHARS_VALIDATION_RE.search(original)):
            raise forms.ValidationError(SLUG_INVALID)

        # Append parent slug data, call super, ensure still valid
        self.cleaned_data['slug'] = self.data['slug'] = (self.parent_slug +
                                                         '/' +
                                                         original)
        # run the parent clean method, checking for collisions
        super(RevisionValidationForm, self).clean_slug()
        self.cleaned_data['slug'] = self.data['slug'] = original
        return self.cleaned_data['slug']


class TreeMoveForm(forms.Form):
    title = StrippedCharField(min_length=1, max_length=255,
                              required=False,
                              widget=forms.TextInput(
                                  attrs={'placeholder': TITLE_PLACEHOLDER}),
                              label=_lazy(u'Title:'),
                              help_text=_lazy(u'Title of article'),
                              error_messages={'required': TITLE_REQUIRED,
                                              'min_length': TITLE_SHORT,
                                              'max_length': TITLE_LONG})
    slug = StrippedCharField(min_length=1, max_length=255,
                             widget=forms.TextInput(),
                             label=_lazy(u'New slug:'),
                             help_text=_lazy(u'New article URL'),
                             error_messages={'required': SLUG_REQUIRED,
                                             'min_length': SLUG_SHORT,
                                             'max_length': SLUG_LONG})
    locale = StrippedCharField(min_length=2, max_length=5,
                               widget=forms.HiddenInput())

    def clean_slug(self):
        # We only want the slug here; inputting a full URL would lead
        # to disaster.
        if '://' in self.cleaned_data['slug']:
            raise forms.ValidationError('Please enter only the slug to move '
                                        'to, not the full URL.')

        # Removes leading slash and {locale/docs/} if necessary
        # IMPORTANT: This exact same regex is used on the client side, so
        # update both if doing so
        self.cleaned_data['slug'] = SLUG_CLEANSING_RE.sub('', self.cleaned_data['slug'])

        # Remove the trailing slash if one is present, because it
        # will screw up the page move, which doesn't expect one.
        self.cleaned_data['slug'] = self.cleaned_data['slug'].rstrip('/')

        return self.cleaned_data['slug']

    def clean(self):
        cleaned_data = super(TreeMoveForm, self).clean()
        if set(['slug', 'locale']).issubset(cleaned_data):
            slug, locale = cleaned_data['slug'], cleaned_data['locale']
            try:
                valid_slug_parent(slug, locale)
            except Exception, e:
                raise forms.ValidationError(e.args[0])
        return cleaned_data


class DocumentDeletionForm(forms.Form):
    reason = forms.CharField(widget=forms.Textarea(attrs={'autofocus': 'true'}))


class DocumentContentFlagForm(ContentFlagForm):
    flag_type = forms.ChoiceField(
        choices=settings.WIKI_FLAG_REASONS,
        widget=forms.RadioSelect)
