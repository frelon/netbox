import re

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import permission_required
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.core.urlresolvers import reverse
from django.db.models import Count, ProtectedError
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import urlencode

from django_tables2 import RequestConfig
from extras.models import ExportTemplate
from utilities.error_handlers import handle_protectederror
from utilities.forms import ConfirmationForm
from utilities.paginator import EnhancedPaginator
from utilities.views import ObjectListView, BulkImportView, BulkEditView, BulkDeleteView
from ipam.models import Prefix, IPAddress, VLAN
from circuits.models import Circuit

from .filters import RackFilter, DeviceFilter, ConsoleConnectionFilter, PowerConnectionFilter, InterfaceConnectionFilter
from .forms import SiteForm, SiteImportForm, RackForm, RackImportForm, RackBulkEditForm, RackBulkDeleteForm, \
    RackFilterForm, DeviceForm, DeviceImportForm, DeviceBulkEditForm, DeviceBulkDeleteForm, DeviceFilterForm, \
    ConsolePortForm, ConsolePortCreateForm, ConsolePortConnectionForm, ConsoleConnectionImportForm, \
    ConsoleServerPortForm, ConsoleServerPortCreateForm, ConsoleServerPortConnectionForm, PowerPortForm, \
    PowerPortCreateForm, PowerPortConnectionForm, PowerConnectionImportForm, PowerOutletForm, PowerOutletCreateForm, \
    PowerOutletConnectionForm, InterfaceForm, InterfaceCreateForm, InterfaceBulkCreateForm, InterfaceConnectionForm, \
    InterfaceConnectionDeletionForm, InterfaceConnectionImportForm, ConsoleConnectionFilterForm, \
    PowerConnectionFilterForm, InterfaceConnectionFilterForm, IPAddressForm
from .models import Site, Rack, Device, ConsolePort, ConsoleServerPort, PowerPort, \
    PowerOutlet, Interface, InterfaceConnection, Module, CONNECTION_STATUS_CONNECTED
from .tables import SiteTable, RackTable, RackBulkEditTable, DeviceTable, DeviceBulkEditTable, DeviceImportTable, \
    ConsoleConnectionTable, PowerConnectionTable, InterfaceConnectionTable


EXPANSION_PATTERN = '\[(\d+-\d+)\]'


def xstr(s):
    """
    Replace None with an empty string (for CSV export)
    """
    return '' if s is None else str(s)


def expand_pattern(string):
    """
    Expand a numeric pattern into a list of strings. Examples:
      'ge-0/0/[0-3]' => ['ge-0/0/0', 'ge-0/0/1', 'ge-0/0/2', 'ge-0/0/3']
      'xe-0/[0-3]/[0-7]' => ['xe-0/0/0', 'xe-0/0/1', 'xe-0/0/2', ... 'xe-0/3/5', 'xe-0/3/6', 'xe-0/3/7']
    """
    lead, pattern, remnant = re.split(EXPANSION_PATTERN, string, maxsplit=1)
    x, y = pattern.split('-')
    for i in range(int(x), int(y) + 1):
        if remnant:
            for string in expand_pattern(remnant):
                yield "{0}{1}{2}".format(lead, i, string)
        else:
            yield "{0}{1}".format(lead, i)


#
# Sites
#

def site_list(request):

    queryset = Site.objects.all()

    # Export
    if 'export' in request.GET:
        et = get_object_or_404(ExportTemplate, content_type__model='site', name=request.GET.get('export'))
        response = et.to_response(context_dict={'queryset': queryset}, filename='netbox_sites')
        return response

    site_table = SiteTable(queryset)
    RequestConfig(request, paginate={'per_page': settings.PAGINATE_COUNT, 'klass': EnhancedPaginator}).configure(site_table)

    export_templates = ExportTemplate.objects.filter(content_type__model='site')

    return render(request, 'dcim/site_list.html', {
        'site_table': site_table,
        'export_templates': export_templates,
    })


def site(request, slug):

    site = get_object_or_404(Site, slug=slug)
    stats = {
        'rack_count': Rack.objects.filter(site=site).count(),
        'device_count': Device.objects.filter(rack__site=site).count(),
        'prefix_count': Prefix.objects.filter(site=site).count(),
        'vlan_count': VLAN.objects.filter(site=site).count(),
        'circuit_count': Circuit.objects.filter(site=site).count(),
    }

    return render(request, 'dcim/site.html', {
        'site': site,
        'stats': stats,
    })


@permission_required('dcim.add_site')
def site_add(request):

    if request.method == 'POST':
        form = SiteForm(request.POST)
        if form.is_valid():
            site = form.save()
            messages.success(request, "Added new site: {0}".format(site.name))
            if '_addanother' in request.POST:
                return redirect('dcim:site_add')
            else:
                return redirect('dcim:site', slug=site.slug)

    else:
        form = SiteForm()

    return render(request, 'dcim/site_edit.html', {
        'form': form,
        'cancel_url': reverse('dcim:site_list'),
    })


@permission_required('dcim.change_site')
def site_edit(request, slug):

    site = get_object_or_404(Site, slug=slug)

    if request.method == 'POST':
        form = SiteForm(request.POST, instance=site)
        if form.is_valid():
            site = form.save()
            messages.success(request, "Modified site {0}".format(site.name))
            return redirect('dcim:site', slug=site.slug)

    else:
        form = SiteForm(instance=site)

    return render(request, 'dcim/site_edit.html', {
        'site': site,
        'form': form,
        'cancel_url': reverse('dcim:site', kwargs={'slug': site.slug}),
    })


@permission_required('dcim.delete_site')
def site_delete(request, slug):

    site = get_object_or_404(Site, slug=slug)

    if request.method == 'POST':
        form = ConfirmationForm(request.POST)
        if form.is_valid():
            try:
                site.delete()
                messages.success(request, "Site {0} has been deleted".format(site))
                return redirect('dcim:site_list')
            except ProtectedError, e:
                handle_protectederror(site, request, e)
                return redirect('dcim:site', slug=site.slug)

    else:
        form = ConfirmationForm()

    return render(request, 'dcim/site_delete.html', {
        'site': site,
        'form': form,
        'cancel_url': reverse('dcim:site', kwargs={'slug': site.slug}),
    })


class SiteBulkImportView(PermissionRequiredMixin, BulkImportView):
    permission_required = 'dcim.add_site'
    form = SiteImportForm
    table = SiteTable
    template_name = 'dcim/site_import.html'
    obj_list_url = 'dcim:site_list'


#
# Racks
#

def rack_list(request):

    queryset = Rack.objects.select_related('site').annotate(device_count=Count('devices', distinct=True))
    queryset = RackFilter(request.GET, queryset).qs

    # Export
    if 'export' in request.GET:
        et = get_object_or_404(ExportTemplate, content_type__model='rack', name=request.GET.get('export'))
        response = et.to_response(context_dict={'queryset': queryset}, filename='netbox_racks')
        return response

    # Hot-wire direct to rack view if only one rack was returned
    if queryset.count() == 1:
        return redirect('dcim:rack', pk=queryset[0].pk)

    if request.user.has_perm('dcim.change_rack') or request.user.has_perm('dcim.delete_rack'):
        rack_table = RackBulkEditTable(queryset)
    else:
        rack_table = RackTable(queryset)
    RequestConfig(request, paginate={'per_page': settings.PAGINATE_COUNT, 'klass': EnhancedPaginator}).configure(rack_table)

    export_templates = ExportTemplate.objects.filter(content_type__model='rack')

    return render(request, 'dcim/rack_list.html', {
        'rack_table': rack_table,
        'export_templates': export_templates,
        'filter_form': RackFilterForm(request.GET, label_suffix=''),
    })


def rack(request, pk):

    rack = get_object_or_404(Rack, pk=pk)

    nonracked_devices = Device.objects.filter(rack=rack, position__isnull=True)
    try:
        next_rack = Rack.objects.filter(site=rack.site, name__gt=rack.name).order_by('name')[0]
    except IndexError:
        next_rack = None
    try:
        prev_rack = Rack.objects.filter(site=rack.site, name__lt=rack.name).order_by('-name')[0]
    except IndexError:
        prev_rack = None

    return render(request, 'dcim/rack.html', {
        'rack': rack,
        'nonracked_devices': nonracked_devices,
        'next_rack': next_rack,
        'prev_rack': prev_rack,
        'front_elevation': rack.get_front_elevation(),
        'rear_elevation': rack.get_rear_elevation(),
    })


@permission_required('dcim.add_rack')
def rack_add(request):

    if request.method == 'POST':
        form = RackForm(request.POST)
        if form.is_valid():
            rack = form.save()
            messages.success(request, "Added new rack to {}: {}".format(rack.site.name, rack))
            if '_addanother' in request.POST:
                base_url = reverse('dcim:rack_add')
                params = urlencode({
                    'site': rack.site.pk,
                })
                return HttpResponseRedirect('{}?{}'.format(base_url, params))
            else:
                return redirect('dcim:rack', pk=rack.pk)

    else:
        form = RackForm()

    return render(request, 'dcim/rack_edit.html', {
        'form': form,
        'cancel_url': reverse('dcim:rack_list'),
    })


@permission_required('dcim.change_rack')
def rack_edit(request, pk):

    rack = get_object_or_404(Rack, pk=pk)

    if request.method == 'POST':
        form = RackForm(request.POST, instance=rack)
        if form.is_valid():
            rack = form.save()
            messages.success(request, "Modified rack {0}".format(rack.name))
            return redirect('dcim:rack', pk=rack.pk)

    else:
        form = RackForm(instance=rack)

    return render(request, 'dcim/rack_edit.html', {
        'rack': rack,
        'form': form,
        'cancel_url': reverse('dcim:rack', kwargs={'pk': rack.pk}),
    })


@permission_required('dcim.delete_rack')
def rack_delete(request, pk):

    rack = get_object_or_404(Rack, pk=pk)

    if request.method == 'POST':
        form = ConfirmationForm(request.POST)
        if form.is_valid():
            try:
                rack.delete()
                messages.success(request, "Rack {0} has been deleted".format(rack))
                return redirect('dcim:rack_list')
            except ProtectedError, e:
                handle_protectederror(rack, request, e)
                return redirect('dcim:rack', pk=rack.pk)

    else:
        form = ConfirmationForm()

    return render(request, 'dcim/rack_delete.html', {
        'rack': rack,
        'form': form,
        'cancel_url': reverse('dcim:rack', kwargs={'pk': rack.pk}),
    })


class RackBulkImportView(PermissionRequiredMixin, BulkImportView):
    permission_required = 'dcim.add_rack'
    form = RackImportForm
    table = RackTable
    template_name = 'dcim/rack_import.html'
    obj_list_url = 'dcim:rack_list'


class RackBulkEditView(PermissionRequiredMixin, BulkEditView):
    permission_required = 'dcim.change_rack'
    cls = Rack
    form = RackBulkEditForm
    template_name = 'dcim/rack_bulk_edit.html'
    redirect_url = 'dcim:rack_list'

    def update_objects(self, pk_list, form):

        fields_to_update = {}
        for field in ['site', 'group', 'u_height', 'comments']:
            if form.cleaned_data[field]:
                fields_to_update[field] = form.cleaned_data[field]

        updated_count = self.cls.objects.filter(pk__in=pk_list).update(**fields_to_update)
        messages.success(self.request, "Updated {} racks".format(updated_count))


class RackBulkDeleteView(PermissionRequiredMixin, BulkDeleteView):
    permission_required = 'dcim.delete_rack'
    cls = Rack
    form = RackBulkDeleteForm
    template_name = 'dcim/rack_bulk_delete.html'
    redirect_url = 'dcim:rack_list'


#
# Devices
#

def device_list(request):

    queryset = Device.objects.select_related('device_type', 'device_type__manufacturer', 'device_role', 'rack', 'rack__site', 'primary_ip')
    queryset = DeviceFilter(request.GET, queryset).qs

    # Export
    if 'export' in request.GET:
        et = get_object_or_404(ExportTemplate, content_type__model='device', name=request.GET.get('export'))
        response = et.to_response(context_dict={'queryset': queryset}, filename='netbox_devices')
        return response

    # Hot-wire direct to device view if only one device was returned
    if queryset.count() == 1:
        return redirect('dcim:device', pk=queryset[0].pk)

    if request.user.has_perm('dcim.change_device') or request.user.has_perm('dcim.delete_device'):
        device_table = DeviceBulkEditTable(queryset)
    else:
        device_table = DeviceTable(queryset)
    RequestConfig(request, paginate={'per_page': settings.PAGINATE_COUNT, 'klass': EnhancedPaginator}).configure(device_table)

    export_templates = ExportTemplate.objects.filter(content_type__model='device')

    return render(request, 'dcim/device_list.html', {
        'device_table': device_table,
        'export_templates': export_templates,
        'filter_form': DeviceFilterForm(request.GET, label_suffix=''),
    })


def device(request, pk):

    device = get_object_or_404(Device, pk=pk)
    console_ports = ConsolePort.objects.filter(device=device).select_related('cs_port__device')
    cs_ports = ConsoleServerPort.objects.filter(device=device).select_related('connected_console')
    power_ports = PowerPort.objects.filter(device=device).select_related('power_outlet__device')
    power_outlets = PowerOutlet.objects.filter(device=device).select_related('connected_port')
    interfaces = Interface.objects.filter(device=device, mgmt_only=False).select_related('connected_as_a', 'connected_as_b', 'circuit')
    mgmt_interfaces = Interface.objects.filter(device=device, mgmt_only=True).select_related('connected_as_a', 'connected_as_b', 'circuit')

    # Gather any secrets which belong to this device
    secrets = device.secrets.all()

    # Find all IP addresses assigned to this device
    ip_addresses = IPAddress.objects.filter(interface__device=device).select_related('interface').order_by('interface')

    # Find any related devices for convenient linking in the UI
    related_devices = []
    if device.name:
        if re.match('.+[0-9]+$', device.name):
            # Strip 1 or more trailing digits (e.g. core-switch1)
            base_name = re.match('(.*?)[0-9]+$', device.name).group(1)
        elif re.match('.+\d[a-z]+$', device.name.lower()):
            # Strip a trailing letter if preceded by a digit (e.g. dist-switch3a -> dist-switch3)
            base_name = re.match('(.*\d+)[a-z]$', device.name.lower()).group(1)
        else:
            base_name = None
        if base_name:
            related_devices = Device.objects.filter(name__istartswith=base_name).exclude(pk=device.pk).select_related('rack', 'device_type__manufacturer')[:10]

    return render(request, 'dcim/device.html', {
        'device': device,
        'console_ports': console_ports,
        'cs_ports': cs_ports,
        'power_ports': power_ports,
        'power_outlets': power_outlets,
        'interfaces': interfaces,
        'mgmt_interfaces': mgmt_interfaces,
        'ip_addresses': ip_addresses,
        'secrets': secrets,
        'related_devices': related_devices,
    })


@permission_required('dcim.add_device')
def device_add(request):

    if request.method == 'POST':
        form = DeviceForm(request.POST)
        if form.is_valid():
            device = form.save()
            messages.success(request, "Added new device: {0} ({1})".format(device.name, device.device_type))
            if '_addanother' in request.POST:
                base_url = reverse('dcim:device_add')
                params = urlencode({
                    'site': device.rack.site.pk,
                    'rack': device.rack.pk,
                })
                return HttpResponseRedirect('{}?{}'.format(base_url, params))
            else:
                return redirect('dcim:device', pk=device.pk)

    else:
        initial_data = {}
        if request.GET.get('rack', None):
            try:
                rack = Rack.objects.get(pk=request.GET.get('rack', None))
                initial_data['rack'] = rack.pk
                initial_data['site'] = rack.site.pk
                initial_data['position'] = request.GET.get('position')
                initial_data['face'] = request.GET.get('face')
            except Rack.DoesNotExist:
                pass
        form = DeviceForm(initial=initial_data)

    return render(request, 'dcim/device_edit.html', {
        'form': form,
        'cancel_url': reverse('dcim:device_list'),
    })


@permission_required('dcim.change_device')
def device_edit(request, pk):

    device = get_object_or_404(Device, pk=pk)

    if request.method == 'POST':
        form = DeviceForm(request.POST, instance=device)
        if form.is_valid():
            device = form.save()
            messages.success(request, "Modified device {0}".format(device.name))
            return redirect('dcim:device', pk=device.pk)

    else:
        form = DeviceForm(instance=device)

    return render(request, 'dcim/device_edit.html', {
        'device': device,
        'form': form,
        'cancel_url': reverse('dcim:device', kwargs={'pk': device.pk}),
    })


@permission_required('dcim.delete_device')
def device_delete(request, pk):

    device = get_object_or_404(Device, pk=pk)

    if request.method == 'POST':
        form = ConfirmationForm(request.POST)
        if form.is_valid():
            try:
                device.delete()
                messages.success(request, "Device {0} has been deleted".format(device))
                return redirect('dcim:device_list')
            except ProtectedError, e:
                handle_protectederror(device, request, e)
                return redirect('dcim:device', pk=device.pk)

    else:
        form = ConfirmationForm()

    return render(request, 'dcim/device_delete.html', {
        'device': device,
        'form': form,
        'cancel_url': reverse('dcim:device', kwargs={'pk': device.pk}),
    })


class DeviceBulkImportView(PermissionRequiredMixin, BulkImportView):
    permission_required = 'dcim.add_device'
    form = DeviceImportForm
    table = DeviceImportTable
    template_name = 'dcim/device_import.html'
    obj_list_url = 'dcim:device_list'


class DeviceBulkEditView(PermissionRequiredMixin, BulkEditView):
    permission_required = 'dcim.change_device'
    cls = Device
    form = DeviceBulkEditForm
    template_name = 'dcim/device_bulk_edit.html'
    redirect_url = 'dcim:device_list'

    def update_objects(self, pk_list, form):

        fields_to_update = {}
        if form.cleaned_data['platform']:
            fields_to_update['platform'] = form.cleaned_data['platform']
        elif form.cleaned_data['platform_delete']:
            fields_to_update['platform'] = None
        if form.cleaned_data['status']:
            status = form.cleaned_data['status']
            fields_to_update['status'] = True if status == 'True' else False
        for field in ['device_type', 'device_role', 'serial', 'ro_snmp']:
            if form.cleaned_data[field]:
                fields_to_update[field] = form.cleaned_data[field]

        updated_count = self.cls.objects.filter(pk__in=pk_list).update(**fields_to_update)
        messages.success(self.request, "Updated {} devices".format(updated_count))


class DeviceBulkDeleteView(PermissionRequiredMixin, BulkDeleteView):
    permission_required = 'dcim.delete_device'
    cls = Device
    form = DeviceBulkDeleteForm
    template_name = 'dcim/device_bulk_delete.html'
    redirect_url = 'dcim:device_list'


def device_inventory(request, pk):

    device = get_object_or_404(Device, pk=pk)
    modules = Module.objects.filter(device=device)

    return render(request, 'dcim/device_inventory.html', {
        'device': device,
        'modules': modules,
    })


def device_lldp_neighbors(request, pk):

    device = get_object_or_404(Device, pk=pk)
    interfaces = Interface.objects.filter(device=device).select_related('connected_as_a', 'connected_as_b')

    return render(request, 'dcim/device_lldp_neighbors.html', {
        'device': device,
        'interfaces': interfaces,
    })


#
# Console ports
#

@permission_required('dcim.add_consoleport')
def consoleport_add(request, pk):

    device = get_object_or_404(Device, pk=pk)

    if request.method == 'POST':
        form = ConsolePortCreateForm(request.POST)
        if form.is_valid():

            console_ports = []
            for name in form.cleaned_data['name_pattern']:
                cp_form = ConsolePortForm({
                    'device': device.pk,
                    'name': name,
                })
                if cp_form.is_valid():
                    console_ports.append(cp_form.save(commit=False))
                else:
                    form.add_error('name_pattern', "Duplicate console port name for this device: {}".format(name))

            if not form.errors:
                ConsolePort.objects.bulk_create(console_ports)
                messages.success(request, "Added {} console port(s) to {}".format(len(console_ports), device))
                if '_addanother' in request.POST:
                    return redirect('dcim:consoleport_add', pk=device.pk)
                else:
                    return redirect('dcim:device', pk=device.pk)

    else:
        form = ConsolePortCreateForm()

    return render(request, 'dcim/consoleport_edit.html', {
        'device': device,
        'form': form,
        'cancel_url': reverse('dcim:device', kwargs={'pk': device.pk}),
    })


@permission_required('dcim.change_consoleport')
def consoleport_connect(request, pk):

    consoleport = get_object_or_404(ConsolePort, pk=pk)

    if request.method == 'POST':
        form = ConsolePortConnectionForm(request.POST, instance=consoleport)
        if form.is_valid():
            consoleport = form.save()
            messages.success(request, "Connected {0} {1} to {2} {3}".format(
                consoleport.device,
                consoleport.name,
                consoleport.cs_port.device,
                consoleport.cs_port.name,
            ))
            return redirect('dcim:device', pk=consoleport.device.pk)

    else:
        form = ConsolePortConnectionForm(instance=consoleport, initial={
            'rack': consoleport.device.rack,
            'connection_status': CONNECTION_STATUS_CONNECTED,
        })

    return render(request, 'dcim/consoleport_connect.html', {
        'consoleport': consoleport,
        'form': form,
        'cancel_url': reverse('dcim:device', kwargs={'pk': consoleport.device.pk}),
    })


@permission_required('dcim.change_consoleport')
def consoleport_disconnect(request, pk):

    consoleport = get_object_or_404(ConsolePort, pk=pk)

    if not consoleport.cs_port:
        messages.warning(request, "Cannot disconnect console port {0}: It is not connected to anything".format(consoleport))
        return redirect('dcim:device', pk=consoleport.device.pk)

    if request.method == 'POST':
        form = ConfirmationForm(request.POST)
        if form.is_valid():
            consoleport.cs_port = None
            consoleport.connection_status = None
            consoleport.save()
            messages.success(request, "Console port {0} has been disconnected".format(consoleport))
            return redirect('dcim:device', pk=consoleport.device.pk)

    else:
        form = ConfirmationForm()

    return render(request, 'dcim/consoleport_disconnect.html', {
        'consoleport': consoleport,
        'form': form,
        'cancel_url': reverse('dcim:device', kwargs={'pk': consoleport.device.pk}),
    })


@permission_required('dcim.change_consoleport')
def consoleport_edit(request, pk):

    consoleport = get_object_or_404(ConsolePort, pk=pk)

    if request.method == 'POST':
        form = ConsolePortForm(request.POST, instance=consoleport)
        if form.is_valid():
            consoleport = form.save()
            messages.success(request, "Modified {0} {1}".format(consoleport.device.name, consoleport.name))
            return redirect('dcim:device', pk=consoleport.device.pk)

    else:
        form = ConsolePortForm(instance=consoleport)

    return render(request, 'dcim/consoleport_edit.html', {
        'consoleport': consoleport,
        'form': form,
        'cancel_url': reverse('dcim:device', kwargs={'pk': consoleport.device.pk}),
    })


@permission_required('dcim.delete_consoleport')
def consoleport_delete(request, pk):

    consoleport = get_object_or_404(ConsolePort, pk=pk)

    if request.method == 'POST':
        form = ConfirmationForm(request.POST)
        if form.is_valid():
            consoleport.delete()
            messages.success(request, "Console port {0} has been deleted from {1}".format(consoleport, consoleport.device))
            return redirect('dcim:device', pk=consoleport.device.pk)

    else:
        form = ConfirmationForm()

    return render(request, 'dcim/consoleport_delete.html', {
        'consoleport': consoleport,
        'form': form,
        'cancel_url': reverse('dcim:device', kwargs={'pk': consoleport.device.pk}),
    })


class ConsoleConnectionsBulkImportView(PermissionRequiredMixin, BulkImportView):
    permission_required = 'dcim.change_consoleport'
    form = ConsoleConnectionImportForm
    table = ConsoleConnectionTable
    template_name = 'dcim/console_connections_import.html'


#
# Console server ports
#

@permission_required('dcim.add_consoleserverport')
def consoleserverport_add(request, pk):

    device = get_object_or_404(Device, pk=pk)

    if request.method == 'POST':
        form = ConsoleServerPortCreateForm(request.POST)
        if form.is_valid():

            cs_ports = []
            for name in form.cleaned_data['name_pattern']:
                csp_form = ConsoleServerPortForm({
                    'device': device.pk,
                    'name': name,
                })
                if csp_form.is_valid():
                    cs_ports.append(csp_form.save(commit=False))
                else:
                    form.add_error('name_pattern', "Duplicate console server port name for this device: {}"
                                   .format(name))

            if not form.errors:
                ConsoleServerPort.objects.bulk_create(cs_ports)
                messages.success(request, "Added {} console server port(s) to {}".format(len(cs_ports), device))
                if '_addanother' in request.POST:
                    return redirect('dcim:consoleserverport_add', pk=device.pk)
                else:
                    return redirect('dcim:device', pk=device.pk)

    else:
        form = ConsoleServerPortCreateForm()

    return render(request, 'dcim/consoleserverport_edit.html', {
        'device': device,
        'form': form,
        'cancel_url': reverse('dcim:device', kwargs={'pk': device.pk}),
    })


@permission_required('dcim.change_consoleserverport')
def consoleserverport_connect(request, pk):

    consoleserverport = get_object_or_404(ConsoleServerPort, pk=pk)

    if request.method == 'POST':
        form = ConsoleServerPortConnectionForm(consoleserverport, request.POST)
        if form.is_valid():
            consoleport = form.cleaned_data['port']
            consoleport.cs_port = consoleserverport
            consoleport.connection_status = form.cleaned_data['connection_status']
            consoleport.save()
            messages.success(request, "Connected {0} {1} to {2} {3}".format(
                consoleport.device,
                consoleport.name,
                consoleserverport.device,
                consoleserverport.name,
            ))
            return redirect('dcim:device', pk=consoleserverport.device.pk)

    else:
        form = ConsoleServerPortConnectionForm(consoleserverport, initial={'rack': consoleserverport.device.rack})

    return render(request, 'dcim/consoleserverport_connect.html', {
        'consoleserverport': consoleserverport,
        'form': form,
        'cancel_url': reverse('dcim:device', kwargs={'pk': consoleserverport.device.pk}),
    })


@permission_required('dcim.change_consoleserverport')
def consoleserverport_disconnect(request, pk):

    consoleserverport = get_object_or_404(ConsoleServerPort, pk=pk)

    if not hasattr(consoleserverport, 'connected_console'):
        messages.warning(request, "Cannot disconnect console server port {0}: Nothing is connected to it".format(consoleserverport))
        return redirect('dcim:device', pk=consoleserverport.device.pk)

    if request.method == 'POST':
        form = ConfirmationForm(request.POST)
        if form.is_valid():
            consoleport = consoleserverport.connected_console
            consoleport.cs_port = None
            consoleport.connection_status = None
            consoleport.save()
            messages.success(request, "Console server port {0} has been disconnected".format(consoleserverport))
            return redirect('dcim:device', pk=consoleserverport.device.pk)

    else:
        form = ConfirmationForm()

    return render(request, 'dcim/consoleserverport_disconnect.html', {
        'consoleserverport': consoleserverport,
        'form': form,
        'cancel_url': reverse('dcim:device', kwargs={'pk': consoleserverport.device.pk}),
    })


@permission_required('dcim.change_consoleserverport')
def consoleserverport_edit(request, pk):

    consoleserverport = get_object_or_404(ConsoleServerPort, pk=pk)

    if request.method == 'POST':
        form = ConsoleServerPortForm(request.POST, instance=consoleserverport)
        if form.is_valid():
            consoleserverport = form.save()
            messages.success(request, "Modified {0} {1}".format(consoleserverport.device.name, consoleserverport.name))
            return redirect('dcim:device', pk=consoleserverport.device.pk)

    else:
        form = ConsoleServerPortForm(instance=consoleserverport)

    return render(request, 'dcim/consoleserverport_edit.html', {
        'consoleserverport': consoleserverport,
        'form': form,
        'cancel_url': reverse('dcim:device', kwargs={'pk': consoleserverport.device.pk}),
    })


@permission_required('dcim.delete_consoleserverport')
def consoleserverport_delete(request, pk):

    consoleserverport = get_object_or_404(ConsoleServerPort, pk=pk)

    if request.method == 'POST':
        form = ConfirmationForm(request.POST)
        if form.is_valid():
            consoleserverport.delete()
            messages.success(request, "Console server port {0} has been deleted from {1}".format(consoleserverport, consoleserverport.device))
            return redirect('dcim:device', pk=consoleserverport.device.pk)

    else:
        form = ConfirmationForm()

    return render(request, 'dcim/consoleserverport_delete.html', {
        'consoleserverport': consoleserverport,
        'form': form,
        'cancel_url': reverse('dcim:device', kwargs={'pk': consoleserverport.device.pk}),
    })


#
# Power ports
#

@permission_required('dcim.add_powerport')
def powerport_add(request, pk):

    device = get_object_or_404(Device, pk=pk)

    if request.method == 'POST':
        form = PowerPortCreateForm(request.POST)
        if form.is_valid():

            power_ports = []
            for name in form.cleaned_data['name_pattern']:
                pp_form = PowerPortForm({
                    'device': device.pk,
                    'name': name,
                })
                if pp_form.is_valid():
                    power_ports.append(pp_form.save(commit=False))
                else:
                    form.add_error('name_pattern', "Duplicate power port name for this device: {}".format(name))

            if not form.errors:
                PowerPort.objects.bulk_create(power_ports)
                messages.success(request, "Added {} power port(s) to {}".format(len(power_ports), device))
                if '_addanother' in request.POST:
                    return redirect('dcim:powerport_add', pk=device.pk)
                else:
                    return redirect('dcim:device', pk=device.pk)

    else:
        form = PowerPortCreateForm()

    return render(request, 'dcim/powerport_edit.html', {
        'device': device,
        'form': form,
        'cancel_url': reverse('dcim:device', kwargs={'pk': device.pk}),
    })


@permission_required('dcim.change_powerport')
def powerport_connect(request, pk):

    powerport = get_object_or_404(PowerPort, pk=pk)

    if request.method == 'POST':
        form = PowerPortConnectionForm(request.POST, instance=powerport)
        if form.is_valid():
            powerport = form.save()
            messages.success(request, "Connected {0} {1} to {2} {3}".format(
                powerport.device,
                powerport.name,
                powerport.power_outlet.device,
                powerport.power_outlet.name,
            ))
            return redirect('dcim:device', pk=powerport.device.pk)

    else:
        form = PowerPortConnectionForm(instance=powerport, initial={
            'rack': powerport.device.rack,
            'connection_status': CONNECTION_STATUS_CONNECTED,
        })

    return render(request, 'dcim/powerport_connect.html', {
        'powerport': powerport,
        'form': form,
        'cancel_url': reverse('dcim:device', kwargs={'pk': powerport.device.pk}),
    })


@permission_required('dcim.change_powerport')
def powerport_disconnect(request, pk):

    powerport = get_object_or_404(PowerPort, pk=pk)

    if not powerport.power_outlet:
        messages.warning(request, "Cannot disconnect power port {0}: It is not connected to an outlet".format(powerport))
        return redirect('dcim:device', pk=powerport.device.pk)

    if request.method == 'POST':
        form = ConfirmationForm(request.POST)
        if form.is_valid():
            powerport.power_outlet = None
            powerport.connection_status = None
            powerport.save()
            messages.success(request, "Power port {0} has been disconnected".format(powerport))
            return redirect('dcim:device', pk=powerport.device.pk)

    else:
        form = ConfirmationForm()

    return render(request, 'dcim/powerport_disconnect.html', {
        'powerport': powerport,
        'form': form,
        'cancel_url': reverse('dcim:device', kwargs={'pk': powerport.device.pk}),
    })


@permission_required('dcim.change_powerport')
def powerport_edit(request, pk):

    powerport = get_object_or_404(PowerPort, pk=pk)

    if request.method == 'POST':
        form = PowerPortForm(request.POST, instance=powerport)
        if form.is_valid():
            powerport = form.save()
            messages.success(request, "Modified {0} power port {1}".format(powerport.device.name, powerport.name))
            return redirect('dcim:device', pk=powerport.device.pk)

    else:
        form = PowerPortForm(instance=powerport)

    return render(request, 'dcim/powerport_edit.html', {
        'powerport': powerport,
        'form': form,
        'cancel_url': reverse('dcim:device', kwargs={'pk': powerport.device.pk}),
    })


@permission_required('dcim.delete_powerport')
def powerport_delete(request, pk):

    powerport = get_object_or_404(PowerPort, pk=pk)

    if request.method == 'POST':
        form = ConfirmationForm(request.POST)
        if form.is_valid():
            powerport.delete()
            messages.success(request, "Power port {0} has been deleted from {1}".format(powerport, powerport.device))
            return redirect('dcim:device', pk=powerport.device.pk)

    else:
        form = ConfirmationForm()

    return render(request, 'dcim/powerport_delete.html', {
        'powerport': powerport,
        'form': form,
        'cancel_url': reverse('dcim:device', kwargs={'pk': powerport.device.pk}),
    })


class PowerConnectionsBulkImportView(PermissionRequiredMixin, BulkImportView):
    permission_required = 'dcim.change_powerport'
    form = PowerConnectionImportForm
    table = PowerConnectionTable
    template_name = 'dcim/power_connections_import.html'


#
# Power outlets
#

@permission_required('dcim.add_poweroutlet')
def poweroutlet_add(request, pk):

    device = get_object_or_404(Device, pk=pk)

    if request.method == 'POST':
        form = PowerOutletCreateForm(request.POST)
        if form.is_valid():

            power_outlets = []
            for name in form.cleaned_data['name_pattern']:
                po_form = PowerOutletForm({
                    'device': device.pk,
                    'name': name,
                })
                if po_form.is_valid():
                    power_outlets.append(po_form.save(commit=False))
                else:
                    form.add_error('name_pattern', "Duplicate power outlet name for this device: {}".format(name))

            if not form.errors:
                PowerOutlet.objects.bulk_create(power_outlets)
                messages.success(request, "Added {} power outlet(s) to {}".format(len(power_outlets), device))
                if '_addanother' in request.POST:
                    return redirect('dcim:poweroutlet_add', pk=device.pk)
                else:
                    return redirect('dcim:device', pk=device.pk)

    else:
        form = PowerOutletCreateForm()

    return render(request, 'dcim/poweroutlet_edit.html', {
        'device': device,
        'form': form,
        'cancel_url': reverse('dcim:device', kwargs={'pk': device.pk}),
    })


@permission_required('dcim.change_poweroutlet')
def poweroutlet_connect(request, pk):

    poweroutlet = get_object_or_404(PowerOutlet, pk=pk)

    if request.method == 'POST':
        form = PowerOutletConnectionForm(poweroutlet, request.POST)
        if form.is_valid():
            powerport = form.cleaned_data['port']
            powerport.power_outlet = poweroutlet
            powerport.connection_status = form.cleaned_data['connection_status']
            powerport.save()
            messages.success(request, "Connected {0} {1} to {2} {3}".format(
                powerport.device,
                powerport.name,
                poweroutlet.device,
                poweroutlet.name,
            ))
            return redirect('dcim:device', pk=poweroutlet.device.pk)

    else:
        form = PowerOutletConnectionForm(poweroutlet, initial={'rack': poweroutlet.device.rack})

    return render(request, 'dcim/poweroutlet_connect.html', {
        'poweroutlet': poweroutlet,
        'form': form,
        'cancel_url': reverse('dcim:device', kwargs={'pk': poweroutlet.device.pk}),
    })


@permission_required('dcim.change_poweroutlet')
def poweroutlet_disconnect(request, pk):

    poweroutlet = get_object_or_404(PowerOutlet, pk=pk)

    if not hasattr(poweroutlet, 'connected_port'):
        messages.warning(request, "Cannot disconnectpower outlet {0}: Nothing is connected to it".format(poweroutlet))
        return redirect('dcim:device', pk=poweroutlet.device.pk)

    if request.method == 'POST':
        form = ConfirmationForm(request.POST)
        if form.is_valid():
            powerport = poweroutlet.connected_port
            powerport.power_outlet = None
            powerport.connection_status = None
            powerport.save()
            messages.success(request, "Power outlet {0} has been disconnected".format(poweroutlet))
            return redirect('dcim:device', pk=poweroutlet.device.pk)

    else:
        form = ConfirmationForm()

    return render(request, 'dcim/poweroutlet_disconnect.html', {
        'poweroutlet': poweroutlet,
        'form': form,
        'cancel_url': reverse('dcim:device', kwargs={'pk': poweroutlet.device.pk}),
    })


@permission_required('dcim.change_poweroutlet')
def poweroutlet_edit(request, pk):

    poweroutlet = get_object_or_404(PowerOutlet, pk=pk)

    if request.method == 'POST':
        form = PowerOutletForm(request.POST, instance=poweroutlet)
        if form.is_valid():
            poweroutlet = form.save()
            messages.success(request, "Modified {0} power outlet {1}".format(poweroutlet.device.name, poweroutlet.name))
            return redirect('dcim:device', pk=poweroutlet.device.pk)

    else:
        form = PowerOutletForm(instance=poweroutlet)

    return render(request, 'dcim/poweroutlet_edit.html', {
        'poweroutlet': poweroutlet,
        'form': form,
        'cancel_url': reverse('dcim:device', kwargs={'pk': poweroutlet.device.pk}),
    })


@permission_required('dcim.delete_poweroutlet')
def poweroutlet_delete(request, pk):

    poweroutlet = get_object_or_404(PowerOutlet, pk=pk)

    if request.method == 'POST':
        form = ConfirmationForm(request.POST)
        if form.is_valid():
            poweroutlet.delete()
            messages.success(request, "Power outlet {0} has been deleted from {1}".format(poweroutlet, poweroutlet.device))
            return redirect('dcim:device', pk=poweroutlet.device.pk)

    else:
        form = ConfirmationForm()

    return render(request, 'dcim/poweroutlet_delete.html', {
        'poweroutlet': poweroutlet,
        'form': form,
        'cancel_url': reverse('dcim:device', kwargs={'pk': poweroutlet.device.pk}),
    })


#
# Interfaces
#

@permission_required('dcim.add_interface')
def interface_add(request, pk):

    device = get_object_or_404(Device, pk=pk)

    if request.method == 'POST':
        form = InterfaceCreateForm(request.POST)
        if form.is_valid():

            interfaces = []
            for name in form.cleaned_data['name_pattern']:
                iface_form = InterfaceForm({
                    'device': device.pk,
                    'name': name,
                    'form_factor': form.cleaned_data['form_factor'],
                    'mgmt_only': form.cleaned_data['mgmt_only'],
                    'description': form.cleaned_data['description'],
                })
                if iface_form.is_valid():
                    interfaces.append(iface_form.save(commit=False))
                else:
                    form.add_error('name_pattern', "Duplicate interface name for this device: {}".format(name))

            if not form.errors:
                Interface.objects.bulk_create(interfaces)
                messages.success(request, "Added {} interface(s) to {}".format(len(interfaces), device))
                if '_addanother' in request.POST:
                    return redirect('dcim:interface_add', pk=device.pk)
                else:
                    return redirect('dcim:device', pk=device.pk)

    else:
        form = InterfaceCreateForm()

    return render(request, 'dcim/interface_edit.html', {
        'device': device,
        'form': form,
        'cancel_url': reverse('dcim:device', kwargs={'pk': device.pk}),
    })


@permission_required('dcim.change_interface')
def interface_edit(request, pk):

    interface = get_object_or_404(Interface, pk=pk)

    if request.method == 'POST':
        form = InterfaceForm(request.POST, instance=interface)
        if form.is_valid():
            interface = form.save()
            messages.success(request, "Modified {0} interface {1}".format(interface.device.name, interface.name))
            return redirect('dcim:device', pk=interface.device.pk)

    else:
        form = InterfaceForm(instance=interface)

    return render(request, 'dcim/interface_edit.html', {
        'interface': interface,
        'form': form,
        'cancel_url': reverse('dcim:device', kwargs={'pk': interface.device.pk}),
    })


@permission_required('dcim.delete_interface')
def interface_delete(request, pk):

    interface = get_object_or_404(Interface, pk=pk)

    if request.method == 'POST':
        form = ConfirmationForm(request.POST)
        if form.is_valid():
            interface.delete()
            messages.success(request, "Interface {0} has been deleted from {1}".format(interface, interface.device))
            return redirect('dcim:device', pk=interface.device.pk)

    else:
        form = ConfirmationForm()

    return render(request, 'dcim/interface_delete.html', {
        'interface': interface,
        'form': form,
        'cancel_url': reverse('dcim:device', kwargs={'pk': interface.device.pk}),
    })


class InterfaceBulkAddView(PermissionRequiredMixin, BulkEditView):
    permission_required = 'dcim.add_interface'
    cls = Device
    form = InterfaceBulkCreateForm
    template_name = 'dcim/interface_bulk_add.html'
    redirect_url = 'dcim:device_list'

    def update_objects(self, pk_list, form):

        selected_devices = Device.objects.filter(pk__in=pk_list)
        interfaces = []

        for device in selected_devices:
            for name in form.cleaned_data['name_pattern']:
                iface_form = InterfaceForm({
                    'device': device.pk,
                    'name': name,
                    'form_factor': form.cleaned_data['form_factor'],
                    'mgmt_only': form.cleaned_data['mgmt_only'],
                    'description': form.cleaned_data['description'],
                })
                if iface_form.is_valid():
                    interfaces.append(iface_form.save(commit=False))
                else:
                    form.add_error(None, "Duplicate interface {} found for device {}".format(name, device))

        if not form.errors:
            Interface.objects.bulk_create(interfaces)
            messages.success(self.request, "Added {} interfaces to {} devices".format(len(interfaces),
                                                                                      len(selected_devices)))


#
# Interface connections
#

@permission_required('dcim.add_interfaceconnection')
def interfaceconnection_add(request, pk):

    device = get_object_or_404(Device, pk=pk)

    if request.method == 'POST':
        form = InterfaceConnectionForm(device, request.POST)
        if form.is_valid():
            interfaceconnection = form.save()
            messages.success(request, "Connected {0} {1} to {2} {3}".format(
                interfaceconnection.interface_a.device,
                interfaceconnection.interface_a,
                interfaceconnection.interface_b.device,
                interfaceconnection.interface_b,
            ))
            if '_addanother' in request.POST:
                base_url = reverse('dcim:interfaceconnection_add', kwargs={'pk': device.pk})
                params = urlencode({
                    'rack_b': interfaceconnection.interface_b.device.rack.pk,
                    'device_b': interfaceconnection.interface_b.device.pk,
                })
                return HttpResponseRedirect('{}?{}'.format(base_url, params))
            else:
                return redirect('dcim:device', pk=device.pk)

    else:
        form = InterfaceConnectionForm(device, initial={
            'interface_a': request.GET.get('interface', None),
            'rack_b': request.GET.get('rack_b', None),
            'device_b': request.GET.get('device_b', None),
        })

    return render(request, 'dcim/interfaceconnection_edit.html', {
        'device': device,
        'form': form,
        'cancel_url': reverse('dcim:device', kwargs={'pk': device.pk}),
    })


@permission_required('dcim.delete_interfaceconnection')
def interfaceconnection_delete(request, pk):

    interfaceconnection = get_object_or_404(InterfaceConnection, pk=pk)
    device_id = request.GET.get('device', None)

    if request.method == 'POST':
        form = InterfaceConnectionDeletionForm(request.POST)
        if form.is_valid():
            interfaceconnection.delete()
            messages.success(request, "Deleted the connection between {0} {1} and {2} {3}".format(
                interfaceconnection.interface_a.device,
                interfaceconnection.interface_a,
                interfaceconnection.interface_b.device,
                interfaceconnection.interface_b,
            ))
            if form.cleaned_data['device']:
                return redirect('dcim:device', pk=form.cleaned_data['device'].pk)
            else:
                return redirect('dcim:device_list')

    else:
        form = InterfaceConnectionDeletionForm(initial={
            'device': device_id,
        })

    # Determine where to direct user upon cancellation
    if device_id:
        cancel_url = reverse('dcim:device', kwargs={'pk': device_id})
    else:
        cancel_url = reverse('dcim:device_list')

    return render(request, 'dcim/interfaceconnection_delete.html', {
        'interfaceconnection': interfaceconnection,
        'device_id': device_id,
        'form': form,
        'cancel_url': cancel_url,
    })


class InterfaceConnectionsBulkImportView(PermissionRequiredMixin, BulkImportView):
    permission_required = 'dcim.change_interface'
    form = InterfaceConnectionImportForm
    table = InterfaceConnectionTable
    template_name = 'dcim/interface_connections_import.html'


#
# Connections
#

class ConsoleConnectionsListView(ObjectListView):
    queryset = ConsolePort.objects.select_related('device', 'cs_port__device').filter(cs_port__isnull=False)\
        .order_by('cs_port__device__name', 'cs_port__name')
    filter = ConsoleConnectionFilter
    filter_form = ConsoleConnectionFilterForm
    table = ConsoleConnectionTable
    template_name = 'dcim/console_connections_list.html'


class PowerConnectionsListView(ObjectListView):
    queryset = PowerPort.objects.select_related('device', 'power_outlet__device').filter(power_outlet__isnull=False)\
        .order_by('power_outlet__device__name', 'power_outlet__name')
    filter = PowerConnectionFilter
    filter_form = PowerConnectionFilterForm
    table = PowerConnectionTable
    template_name = 'dcim/power_connections_list.html'


class InterfaceConnectionsListView(ObjectListView):
    queryset = InterfaceConnection.objects.select_related('interface_a__device', 'interface_b__device')\
        .order_by('interface_a__device__name', 'interface_a__name')
    filter = InterfaceConnectionFilter
    filter_form = InterfaceConnectionFilterForm
    table = InterfaceConnectionTable
    template_name = 'dcim/interface_connections_list.html'


#
# IP addresses
#

@permission_required('ipam.add_ipaddress')
def ipaddress_assign(request, pk):

    device = get_object_or_404(Device, pk=pk)

    if request.method == 'POST':
        form = IPAddressForm(device, request.POST)
        if form.is_valid():

            ipaddress = form.save(commit=False)
            ipaddress.interface = form.cleaned_data['interface']
            ipaddress.save()
            messages.success(request, "Added new IP address {0} to interface {1}".format(ipaddress, ipaddress.interface))

            if form.cleaned_data['set_as_primary']:
                device.primary_ip = ipaddress
                device.save()

            if '_addanother' in request.POST:
                return redirect('dcim:ipaddress_assign', pk=device.pk)
            else:
                return redirect('dcim:device', pk=device.pk)

    else:
        form = IPAddressForm(device)

    return render(request, 'dcim/ipaddress_assign.html', {
        'device': device,
        'form': form,
        'cancel_url': reverse('dcim:device', kwargs={'pk': device.pk}),
    })
