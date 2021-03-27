#! /usr/bin/env perl

use warnings;
use strict;

use Carp;
use File::Basename;
use File::Spec;

my $ishlib_name    = "ishlib";
my $ishlib_version = '';

my $base_fn   = 'src/base.sh';
my $readme_fn = 'src/readme_src.md';

my $header_end =
'###############################################################################';

# my $ishlib = File::Spec->catfile(getcwd(), 'ishlib.sh');

my $readme_documentation_start = "## Documentation";

my $src_dir = dirname($base_fn);

my $current_fn  = $base_fn;
my $empty_lines = 0;

sub set_version {
    my ( $sec, $min, $hour, $mday, $mon, $year, $wday, $yday, $isdst ) =
      localtime();
    my $git_revision = `git rev-parse --short HEAD`;
    chomp $git_revision;

    $ishlib_version = sprintf(
        "%04d-%02d-%02d.%02d%02d.%s",
        $year + 1900,
        $mon + 1, $mday, $hour, $min, $git_revision
    );
    return;
}

sub source_readme {
    my ( $out_fh, $fn_base ) = @_;
    my $fn = $readme_fn;

    print "Inserting $fn\n";

    open my $fh, "<", "$fn" or croak "Failed to open < $fn";
    while (<$fh>) {
        process_oneline( $out_fh, $_ );
        if (m/^$readme_documentation_start\s*$/) {
            close $fh;
            return;
        }
    }
    croak "Unexpected EOF file";
}

sub source_file {
    my ( $out_fh, $fn_base ) = @_;
    my $start_reading = 0;
    my $fn            = File::Spec->catfile( $src_dir, $fn_base );

    print "Sourcing $fn\n";

    my $old_fn = $current_fn;    # Store previous $current_fn
    $current_fn = $fn;           # and set $current_fn to this file

    open my $fh, "<", "$fn" or croak "Failed to open < $fn";
    while (<$fh>) {
        if (m/^$header_end\s*$/) {    # Ignore until we see the header_end
            $start_reading = 1;
        } elsif ($start_reading) {
            process_oneline( $out_fh, $_ );
        }
    }
    close $fh;

    $current_fn = $old_fn;            # Restore $current_fn
    return;
}

sub process_oneline {
    my ( $out_fh, $line ) = @_;

    if ( $line =~ m/^__ISHLIB_README__\s*$/ ) {    # inline README
        source_readme( $out_fh, $_ );
    } elsif ( $line =~ m/^\. ([\w_\.]+)$/ ) {      # inline source
        source_file( $out_fh, $1 );
    } elsif ( $line =~ m/^\s*$/ ) {                # Squash multiple empty lines
        $empty_lines++ or print $out_fh "\n";
    } else {                                       # Otherwise print the line
        $empty_lines = 0;
        $line =~ s/__ISHLIB_VERSION__/$ishlib_version/g;
        $line =~ s/__ISHLIB_NAME__/$ishlib_name/g;
        print $out_fh $line;
    }

    return;
}

sub build_ishlib {
    my $output_fn = shift;
    print "Starting from base  $base_fn\n";

    open my $base_fh, "<", $base_fn   or croak "Failed to open < $base_fn";
    open my $out_fh,  ">", $output_fn or croak "Cannot open > $output_fn";

    while (<$base_fh>) {
        process_oneline( $out_fh, $_ );
    }

    close $base_fh;
    close $out_fh;
    return;
}

sub reset_readme {
    my $fn = shift;
    my @lines = ( "# $ishlib_name $ishlib_version " );

    my $skip = 0;

    open my $fh, "<", $fn   or croak "Failed to open < $fn";
    while (<$fh>) {
        $skip++ or next; # Skip first line
        push @lines, $_;
        m/^$readme_documentation_start\s*$/ and last;
    }
    close $fh;
    return;
}

set_version();

print "Generating ishlib.sh\n";
build_ishlib('ishlib.sh');

1;
