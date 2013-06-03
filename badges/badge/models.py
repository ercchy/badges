from django.core.urlresolvers import reverse
from django.utils.translation import ugettext as _
from datetime import datetime
from .db import Badge
from .db import Award
from .notification_helpers import send_badge_creation_notification
from .notification_helpers import send_badge_awarded_notification


class DuplicateTitleError(Exception):
    pass

class NotTheAuthorError(Exception):
    pass

class HasProjectsAttachedError(Exception):
    pass


def uri2id(uri):
    return uri.strip('/').split('/')[-1]


def id2uri(badge_id):
    return '/uri/badge/%s' % badge_id


def _badge2dict(badge_db):
    badge = {
        'id': badge_db.id,
        'uri': id2uri(badge_db.id),
        'title': badge_db.title,
        'image_uri': badge_db.image_uri,
        'description': badge_db.description,
        'requirements': badge_db.requirements,
        'author_uri': badge_db.author_uri,
        'deleted': badge_db.deleted,
        'partner_name': badge_db.partner_name,
        'publised': badge_db.date_published is not None
    }
    return badge


def create_badge(title, image_uri, description, requirements, author_uri, partner_name=None):
    if Badge.objects.filter(title=title).exists():
        raise DuplicateTitleError('Badge titles need to be unique.')

    badge = Badge(
        title=title, 
        image_uri=image_uri, 
        description=description, 
        requirements=requirements, 
        author_uri=author_uri,
        partner_name=partner_name,
        date_created=datetime.utcnow(),
        date_updated=datetime.utcnow()
    )
    badge.save()

    badge = _badge2dict(badge)
    send_badge_creation_notification(badge)
    return badge


def get_badge(uri):
    badge_db = Badge.objects.get(id=uri2id(uri))
    return _badge2dict(badge_db)


def update_badge(uri, image_uri=None, title=None, description=None, requirements=None, deleted=False):
    """ only possible while draft """
    badge_db = Badge.objects.get(id=uri2id(uri))

    # NOTE: not sure this should be in the API... what if the admin wants
    # to correct a small mistake
    if badge_db.date_published:
        raise Exception(_('Badge cannot be updated after it has been publised'))
    if image_uri:
        badge_db.image_uri = image_uri
    if title:
        if Badge.objects.exclude(id=badge_db.id).filter(title=title).exists():
            raise DuplicateTitleError(_('Badge titles need to be unique.'))
        badge_db.title = title
    if description:
        badge_db.description = description
    if requirements:
        badge_db.requirements = requirements

    badge_db.save()
    return get_badge(uri)


def delete_badge(badge_uri, user_uri):
    """
    Enables owner and admin to archive badge
    """
    from project.processors import search_projects

    badge_db = Badge.objects.get(id=uri2id(badge_uri))

    projects = search_projects(badge_uri=badge_uri)

    if badge_db.author_uri != user_uri:
        raise NotTheAuthorError('You are not the author of the badge')

    if projects:
        raise HasProjectsAttachedError('Badge has projects. It can not be deleted.')

    badge_db.deleted = True
    badge_db.save()

    #TODO: Check if badge in user backpack and revoke

    return _badge2dict(badge_db)


def publish_badge(uri):
    badge_db = Badge.objects.get(id=uri2id(uri))
    badge_db.date_published = datetime.utcnow()
    badge_db.save()
    award_badge(
        uri,
        badge_db.author_uri,
        badge_db.author_uri,
        reverse('badge_view', args=(badge_db.pk, )),
    )
    return True


def remove_badge(uri, reason):
    """ Mark a badge as removed - spam / inappropriate """
    pass


def get_published_badges():
    badges = Badge.objects.filter(deleted=False, date_published__isnull=False)
    return [_badge2dict(badge) for badge in badges]


def get_user_draft_badges(user_uri):
    badges = Badge.objects.filter(author_uri=user_uri, deleted=False, date_published__isnull=True)
    return [_badge2dict(badge) for badge in badges]


def get_user_created_badges(author_uri):
    """ created badges aka 'published' badges """
    badges = Badge.objects.filter(author_uri=author_uri, deleted=False, date_published__isnull=False)
    return [_badge2dict(badge) for badge in badges]


def get_user_earned_badges(user_uri):
    awards = Award.objects.select_related().filter(user_uri=user_uri, badge__deleted=False)
    ret_val = []
    for award in awards:
        badge_dict = _badge2dict(award.badge)
        badge_dict['award_id'] = award.pk
        badge_dict['award_ob_state'] = award.ob_state
        ret_val.append(badge_dict)
    return ret_val


def get_user_awarded_badges(user_uri):
    """ get badges awarded by this user """
    badges = [award.badge for award in Award.objects.select_related().filter(expert_uri=user_uri, badge__deleted=False)]
    return [_badge2dict(badge) for badge in badges]


def award_badge(badge_uri, user_uri, expert_uri, evidence_url):
    """ Award a badge to a user 
        expert_uri - expert that is awarding the badge
    """
    badge = Badge.objects.get(id=uri2id(badge_uri))
    if Award.objects.filter(badge=badge, user_uri=user_uri).exists():
        raise Exception(_('Badge already awarded to user'))

    valid_expert = expert_uri in get_badge_experts(badge_uri)
    badge_creator = user_uri == badge.author_uri

    # Check if we can award the badge
    if not badge_creator and not valid_expert:
        raise Exception('Cannot award badge')

    award = Award(
        badge=badge,
        user_uri=user_uri,
        expert_uri=expert_uri,
        evidence_url=evidence_url,
        date_awarded=datetime.utcnow()
    )
    award.save()

    if not badge_creator:
        send_badge_awarded_notification(get_badge(badge_uri), user_uri)


def get_badge_experts(uri):
    awards = Award.objects.filter(badge_id=uri2id(uri))
    experts = [award.user_uri for award in awards]
    experts = list(set(experts))
    return experts


def relinquish_badge(uri, expert_uri):
    raise Exception()


def award_was_pushed_to_backpack(award_id):
    """
    Signal to us that award was successfully pushed to Open Badges.
    """

    award = Award.objects.get(pk=award_id)
    award.ob_state = 'PUBLISHED'
    award.ob_date_published = datetime.utcnow()
    award.save()
