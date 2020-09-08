from datetime import datetime, timedelta
import pytz
import json
import urllib

from django.http import HttpResponseRedirect
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required

from zoom import zoom_api as zoom
from zoom import secrets

# Show a list of upcoming meetings
@login_required
def meetings(request):
    if 'crash' in request.GET:
        raise Exception('oh no')
    token = zoom.gen_token()
    if 'type' in request.GET:
        meetings, _ = zoom.list_meetings(token, typ=request.GET['type'])
    else:
        meetings, _ = zoom.list_meetings(token)
    return render(request, 'zoom/meetings.html', {'meetings': meetings})

# Show details about a single meeting
# If method==POST, update meeting details first
@login_required
def meeting(request, meeting_id, occurrence_id=None):
    token = zoom.gen_token()
    meeting, _ = zoom.get_meeting(token, meeting_id)

    if request.method == 'POST':
        assert 'ocurrences' not in meeting, 'Editing recurring meetings is not supported'

        updates = {}
        post = {k: urllib.parse.unquote(v) for k, v in request.POST.items()}

        # use a whitelist of properties that can be set
        for prop in ('topic', 'password', 'agenda'):
            updates[prop] = post[prop]

        # start_time is split into three properties
        updates['start_time'] = '%(start_time-date)sT%(start_time-time)s:00' % post
        updates['timezone'] = post['timezone']

        # duration is passed as end_time
        fmt = '%Y-%m-%dT%H:%M:%S'
        start = datetime.strptime(updates['start_time'], fmt)
        end = datetime.strptime('%(start_time-date)sT%(end_time)s:00' % post, fmt)
        updates['duration'] = round((end - start).seconds / 60)

        if post['action'] == 'update':
            # edit the current meeting, then show it again

            try:
                _, code = zoom.update_meeting(token, meeting_id, updates)
                error = ''
            except zoom.Error as e:
                code = e.code
                error = urllib.request.quote(json.dumps(e.data))

            return HttpResponseRedirect('?update=%d&error=%s' % (code, error)) # redirect so that refreshing doesn't POST again

        elif post['action'] == 'create':
            # create a new meeting, then show that one

            for k, v in updates.items():
                meeting[k] = v

            try:
                meeting, code = zoom.create_meeting(token, meeting)
            except zoom.Error as e:
                return HttpResponseRedirect('?update=%d' % code) # redirect so that refreshing doesn't POST again

            return redirect('meeting', meeting_id=meeting['id'])

    # this is now a GET request, show the meeting info

    if meeting['settings']['approval_type'] == 2: # registration not required
        registrants = None
    else:
        registrants, _ = zoom.get_registrants(token, meeting_id)

    # for a recurring meeting, search for a occurrence we want
    if 'occurrences' in meeting:
        for occurrence in meeting['occurrences']:
            if int(occurrence['occurrence_id']) == occurrence_id:
                meeting['start_time'] = occurrence['start_time']
                meeting['duration'] = occurrence['duration']
                break

    data = {'meeting': meeting, 'registrants': registrants}

    try:
        # if it's a past meeting, get attendees (FIXME won't work for recurring meetings)
        if pytz.utc.localize(datetime.strptime(meeting['start_time'], '%Y-%m-%dT%H:%M:%SZ')) + timedelta(minutes=int(meeting['duration'])) < datetime.now(pytz.utc):
            data['participants'], _ = zoom.get_participants(token, meeting_id)
    except Exception as e:
        data['error_message'] = 'Couldn\'t fetch attendee data: %s' % e

    if 'update' in request.GET:
        data['update'] = int(request.GET['update'])
    if 'error' in request.GET:
        data['error'] = zoom.load_json(request.GET['error'])
    return render(request, 'zoom/meeting.html', data)
